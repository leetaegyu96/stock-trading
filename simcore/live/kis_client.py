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
            df = pd.DataFrame(recs).set_index("date").sort_index()
            return df[["open", "high", "low", "close", "volume"]]
        return self._overseas_daily(symbol, start, end)  # Task 4

    # Task 4 에서 정의
    def _overseas_price(self, symbol: str) -> float: ...
    def _overseas_daily(self, symbol, start, end) -> pd.DataFrame: ...
    def market_cap_ranking(self, top_n: int) -> list[str]: ...
