"""KIS 오픈API REST 래퍼 (읽기 전용). 키 마스킹·토큰 캐시·백오프."""
from __future__ import annotations
import time
from datetime import date
from typing import Protocol
import httpx
import pandas as pd

from simcore.live.ratelimit import RateLimiter
from simcore.live.settings import LiveSettings

_TR = {  # (기능, market) -> tr_id
    ("price", "KR"): "FHKST01010100",
    ("daily", "KR"): "FHKST03010100",
    ("rank_mcap", "KR"): "FHPST01740000",
    ("price", "US"): "HHDFS00000300",
    ("daily", "US"): "HHDFS76240000",
}
_EXCD = {"NASDAQ": "NAS", "NYSE": "NYS", "AMEX": "AMS"}


class TokenStore(Protocol):
    def get(self) -> "tuple[str, float] | None": ...
    def save(self, token: str, expires_at: float) -> None: ...


class InMemoryTokenStore:
    def __init__(self) -> None:
        self._v: tuple[str, float] | None = None
    def get(self):
        return self._v
    def save(self, token: str, expires_at: float) -> None:
        self._v = (token, expires_at)


class KisClient:
    def __init__(self, settings: LiveSettings, token_store: TokenStore,
                 limiter: RateLimiter, client: httpx.Client | None = None,
                 clock=time.time, sleep=time.sleep):
        self.s = settings
        self.store = token_store
        self.limiter = limiter
        self.clock = clock
        self.sleep = sleep
        self.http = client or httpx.Client(base_url=settings.kis_base_url(), timeout=10.0)

    # ---- 토큰 ----
    def _token(self) -> str:
        cached = self.store.get()
        if cached and cached[1] - self.clock() > 600:
            return cached[0]
        r = self.http.post("/oauth2/tokenP", json={
            "grant_type": "client_credentials",
            "appkey": self.s.kis_app_key, "appsecret": self.s.kis_app_secret})
        r.raise_for_status()
        j = r.json()
        token = j["access_token"]
        self.store.save(token, self.clock() + float(j.get("expires_in", 86400)))
        return token

    def _headers(self, tr_id: str) -> dict:
        return {"authorization": f"Bearer {self._token()}",
                "appkey": self.s.kis_app_key, "appsecret": self.s.kis_app_secret,
                "tr_id": tr_id, "custtype": "P"}

    def _get(self, path: str, tr_id: str, params: dict) -> dict:
        for attempt in range(3):
            self.limiter.acquire()
            r = self.http.get(path, headers=self._headers(tr_id), params=params)
            if r.status_code == 401:            # 토큰 만료 → 무효화 후 1회 재발급
                self.store.save("", 0.0)
                continue
            if r.status_code in (429, 500, 502, 503):
                self.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"KIS GET 실패: {path}")

    # ---- 국내 시세 ----
    def current_price(self, market: str, symbol: str) -> float:
        if market == "KR":
            j = self._get("/uapi/domestic-stock/v1/quotations/inquire-price",
                          _TR[("price", "KR")],
                          {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol})
            return float(j["output"]["stck_prpr"])
        return self._overseas_price(symbol)   # Task 4

    def execution_strength(self, market: str, symbol: str) -> "float | None":
        """체결강도(매수/매도 체결 비율, 100 기준). KR 만 지원, US 는 None.
        조회·파싱 실패 시 None(호출부가 이 조건을 스킵)."""
        if market != "KR":
            return None
        try:
            j = self._get("/uapi/domestic-stock/v1/quotations/inquire-price",
                           _TR[("price", "KR")],
                           {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol})
            raw = j.get("output", {}).get("cttr")
            return float(raw) if raw not in (None, "") else None
        except Exception:
            return None

    def daily_bars(self, market: str, symbol: str, start: date, end: date) -> pd.DataFrame:
        if market == "KR":
            j = self._get(
                "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                _TR[("daily", "KR")],
                {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol,
                 "FID_INPUT_DATE_1": f"{start:%Y%m%d}", "FID_INPUT_DATE_2": f"{end:%Y%m%d}",
                 "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"})
            rows = j.get("output2", [])
            recs = [{"date": pd.to_datetime(r["stck_bsop_date"]),
                     "open": float(r["stck_oprc"]), "high": float(r["stck_hgpr"]),
                     "low": float(r["stck_lwpr"]), "close": float(r["stck_clpr"]),
                     "volume": float(r["acml_vol"])}
                    for r in rows if r.get("stck_bsop_date")]
            if not recs:
                return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            df = pd.DataFrame(recs).set_index("date").sort_index()
            return df[["open", "high", "low", "close", "volume"]]
        return self._overseas_daily(symbol, start, end)  # Task 4

    # ---- 시총 랭킹(KR) ----
    def market_cap_ranking(self, top_n: int) -> list[str]:
        j = self._get("/uapi/domestic-stock/v1/ranking/market-cap",
                      _TR[("rank_mcap", "KR")],
                      {"fid_cond_mrkt_div_code": "J", "fid_cond_scr_div_code": "20174",
                       "fid_div_cls_code": "0", "fid_input_iscd": "0000",
                       "fid_trgt_cls_code": "0", "fid_trgt_exls_cls_code": "0",
                       "fid_input_price_1": "", "fid_input_price_2": "",
                       "fid_vol_cnt": ""})
        syms = [row["mksc_shrn_iscd"] for row in j.get("output", [])]
        return syms[:top_n]

    # ---- 해외 시세 ----
    def _split_us(self, symbol: str) -> "list[tuple[str, str]]":
        if ":" in symbol:
            exch, tkr = symbol.split(":", 1)
            return [(exch, self._to_kis_ticker(tkr))]
        tkr = self._to_kis_ticker(symbol)
        return [("NAS", tkr), ("NYS", tkr)]

    @staticmethod
    def _to_kis_ticker(ticker: str) -> str:
        """클래스주 표기(BRK-B)를 KIS 해외 API가 요구하는 형식(BRK/B)으로 변환."""
        return ticker.replace("-", "/")

    def _overseas_price(self, symbol: str) -> float:
        for excd, tkr in self._split_us(symbol):
            j = self._get("/uapi/overseas-price/v1/quotations/price",
                          _TR[("price", "US")],
                          {"AUTH": "", "EXCD": excd, "SYMB": tkr})
            out = j.get("output") or {}
            if out.get("last"):
                return float(out["last"])
        raise RuntimeError(f"US 현재가 조회 실패: {symbol}")

    def _overseas_daily(self, symbol, start, end) -> pd.DataFrame:
        for excd, tkr in self._split_us(symbol):
            j = self._get("/uapi/overseas-price/v1/quotations/dailyprice",
                          _TR[("daily", "US")],
                          {"AUTH": "", "EXCD": excd, "SYMB": tkr,
                           "GUBN": "0", "BYMD": f"{end:%Y%m%d}", "MODP": "1"})
            rows = j.get("output2", [])
            if not rows:
                continue
            recs = [{"date": pd.to_datetime(r["xymd"]), "open": float(r["open"]),
                     "high": float(r["high"]), "low": float(r["low"]),
                     "close": float(r["clos"]), "volume": float(r["tvol"])}
                    for r in rows if r.get("xymd")]
            df = pd.DataFrame(recs).set_index("date").sort_index()
            df = df[(df.index.date >= start) & (df.index.date <= end)]
            return df[["open", "high", "low", "close", "volume"]]
        raise RuntimeError(f"US 일봉 조회 실패: {symbol}")
