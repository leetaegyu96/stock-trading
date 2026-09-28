"""시세·종목 리스트 (SPEC §4).

v1 의 `simcore.live.kis_client.KisClient` 를 그대로 재사용하되, **토큰 저장소만 v2 DB 로
분리**한다(SPEC §4.1). 같은 앱키로 v1·v2 가 각자 토큰을 재발급하면 서로를 무효화해
장중에 양쪽 시세가 동시에 끊긴다.

캐시를 두는 이유는 KIS 호출량 제한 때문이다. 종목 리스트는 60초, 일봉은 날짜가 바뀔
때까지 재사용한다(일봉은 하루 한 번만 확정되므로 더 자주 받을 이유가 없다).
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
import time as _time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from simcore import names as _names
from simcore import universe as _universe
from simcore.live.kis_client import KisClient
from simcore.live.ratelimit import RateLimiter
from v2.backend.models import KisToken
from v2.backend.settings import V2Settings
# 시세 실패는 매매 계층과 같은 오류 코드(PRICE_UNAVAILABLE)로 올라가야 HTTP 계층이
# 한 곳에서 매핑할 수 있다. 그래서 예외 타입을 trading 과 공유한다(역방향 의존 없음).
from v2.backend.trading import TradingError

# 종목당 일봉을 한 번 받아 7일·20일·52주 지표를 모두 계산한다 — 호출 1회로 끝내기 위해
# 52주보다 넉넉한 창을 받는다(휴장일 포함 달력일 기준).
_BARS_WINDOW_DAYS = 400
_LIST_TTL_SEC = 60.0
# 한 번에 화면에 내보내는 기본 개수. 유니버스 전체는 이보다 훨씬 크고, 필요한 만큼만
# 상세(현재가·일봉)를 채운다 — 500종목을 한꺼번에 채우면 KIS 호출이 1,000회가 된다.
_PAGE_SIZE = 30
# 유니버스 조회 상한(폴백 경로). 실제 KIS 랭킹은 30행이 상한이라 그 이상은 오지 않지만,
# 페이지 크기와 유니버스 크기를 같은 상수로 묶으면 '더 보기'가 조용히 막힌다.
_UNIVERSE_MAX = 500
_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- 토큰·클라이언트

class DbTokenStore:
    """v2 전용 KIS 토큰 저장소. v1 의 `simcore.live.repository.DbTokenStore` 와 같은
    인터페이스지만 **v2 DB(`kis_token`)** 를 본다(SPEC §4.1)."""

    def __init__(self, session_factory) -> None:
        self.sf = session_factory

    def get(self) -> tuple[str, float] | None:
        with self.sf() as s:              # type: Session
            row = s.get(KisToken, 1)
            if row and row.access_token:
                return row.access_token, float(row.expires_at)
            return None

    def save(self, token: str, expires_at: float) -> None:
        with self.sf() as s:              # type: Session
            row = s.get(KisToken, 1)
            if row is None:
                s.add(KisToken(id=1, access_token=token, expires_at=expires_at))
            else:
                row.access_token, row.expires_at = token, expires_at
            s.commit()


@dataclass(frozen=True)
class _KisSettingsShim:
    """`KisClient` 는 `LiveSettings` 를 기대하지만 실제로 쓰는 필드는 앱키·시크릿·base_url
    셋뿐이다. v2 설정을 v1 타입으로 바꾸지 않고 필요한 면만 맞춘다."""
    kis_app_key: str
    kis_app_secret: str
    base_url: str

    def kis_base_url(self) -> str:
        return self.base_url

    def __repr__(self) -> str:            # 시크릿 마스킹
        return "_KisSettingsShim(kis_app_key='***', kis_app_secret='***')"


# 호출 성격이 달라 타임아웃도 나눈다.
#  - 현재가: 주문·1분 감시의 핫 경로. 길게 잡으면 주문 한 건이 그만큼 멈추고,
#    30종목이 줄줄이 타임아웃하면 감시 주기 자체를 넘긴다.
#  - 일봉·랭킹: 응답이 본래 수 초 걸리고 **하루 1회**만 조회(캐시)하므로 넉넉해야 한다.
#    둘을 같은 값으로 묶으면 한쪽이 반드시 깨진다(실제로 3초 통일 시 일봉이 전부 실패했다).
_QUOTE_TIMEOUT = 3.0
_BARS_TIMEOUT = 20.0
# 실시간 시세 캐시 수명. 성공은 매매 판단이 흔들리지 않을 만큼만 짧게(5초),
# 실패는 감시 한 바퀴를 건너뛸 만큼 길게(30초) 둔다.
_QUOTE_TTL = 5.0
_QUOTE_FAIL_TTL = 30.0
# 목록 조립 동시 실행 수. KIS 레이트리미터(기본 초당 10회)가 상한을 지키므로
# 여기서는 커넥션을 과하게 열지 않을 만큼만 잡는다.
_FETCH_WORKERS = 8
# 위키백과는 pandas 기본 UA 를 403 으로 막는다. 브라우저 UA 면 정상 응답한다.
_WIKI_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def make_kis_client(session_factory, settings: V2Settings) -> KisClient:
    """v2 토큰 저장소를 물린 KIS 클라이언트."""
    shim = _KisSettingsShim(settings.kis_app_key, settings.kis_app_secret,
                            settings.kis_base_url())
    return _make(shim, session_factory, settings, _QUOTE_TIMEOUT)


def make_bars_client(session_factory, settings: V2Settings) -> KisClient:
    """일봉·랭킹용 — 느린 대신 하루 1회만 부르는 경로."""
    shim = _KisSettingsShim(settings.kis_app_key, settings.kis_app_secret,
                            settings.kis_base_url())
    return _make(shim, session_factory, settings, _BARS_TIMEOUT)


def _make(shim, session_factory, settings: V2Settings, timeout: float) -> KisClient:
    # 토큰 저장소·레이트리미터는 공유해도 되지만(같은 앱키), HTTP 클라이언트만 분리한다.
    return KisClient(shim, DbTokenStore(session_factory),
                     RateLimiter(settings.kis_rate_limit_per_sec),
                     client=httpx.Client(base_url=settings.kis_base_url(),
                                         timeout=timeout))


# ---------------------------------------------------------------- 반환 타입

@dataclass(frozen=True)
class StockInfo:
    """매수 화면 한 줄(SPEC §4.2). 점수·추천은 넣지 않는다 — 사실만 제시한다."""
    symbol: str
    name: str
    price: float | None
    change_pct: float | None          # 전일 종가 대비 %
    spark7: list[float] = field(default_factory=list)   # 최근 7거래일 종가
    week_change_pct: float | None = None
    volume: float | None = None
    volume_vs_avg: float | None = None                  # 20일 평균 거래량 대비 배수
    high_52w: float | None = None
    low_52w: float | None = None
    stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StockDetail:
    info: StockInfo
    bars: list[dict[str, Any]]        # 최근 30일 일봉
    kind: str = "KR"                  # 'KR' | 'US'
    currency: str = "KRW"

    def to_dict(self) -> dict[str, Any]:
        # 응답 계약을 **여기 한 곳**에서 닫는다. 라우터가 뒤에서 키를 덧붙이면
        # 직렬화 단위 테스트가 통과해도 실제 응답과 달라진다.
        # 키 이름은 프론트 types.ts 와 반드시 같아야 한다 — "bars" 로 내보내는 동안
        # 상세 화면이 차트를 못 그려 빈 화면이었다.
        return {**self.info.to_dict(), "bars30": self.bars,
                "kind": self.kind, "currency": self.currency}


# ---------------------------------------------------------------- 서비스

def _pct(now_v: float, base: float) -> float | None:
    if base in (0, None):
        return None
    return round((now_v / base - 1.0) * 100.0, 3)


class MarketService:
    """KIS 조회 + 캐시. 스케줄러 스레드와 요청 스레드가 함께 쓰므로 락으로 보호한다."""

    def __init__(self, kis, *, clock=_time.monotonic, today=None,
                 cache_dir: Path | None = None, kis_bars=None) -> None:
        self.kis = kis
        # 일봉·랭킹은 느린 경로라 타임아웃이 다른 클라이언트를 쓴다. 테스트에서 하나만
        # 주입하면 그대로 공유한다(가짜 객체는 어차피 즉시 응답한다).
        self.kis_bars = kis_bars or kis
        self._clock = clock
        self._today_fn = today or (lambda: datetime.now().date())
        self._cache_dir = cache_dir or (_REPO_ROOT / "data" / "cache")
        self._lock = threading.RLock()
        self._bars: dict[tuple[str, str], tuple[date, pd.DataFrame]] = {}
        self._lists: dict[str, tuple[float, list[StockInfo]]] = {}
        self._symbols: dict[str, tuple[date, list[str]]] = {}
        # 현재가 캐시: (만료시각, 가격, stale). 성공은 짧게, **실패는 길게** 캐싱한다 —
        # KIS 가 응답하지 않을 때 종목마다 타임아웃을 거듭 물면 1분 감시가 1분을 넘긴다.
        self._quotes: dict[tuple[str, str], tuple[float, float | None, bool]] = {}
        # 거래소가 알려준 종목명. 정적 이름표에 없는 신규·변경 종목을 메운다.
        self._names: dict[str, str] = {}
        # KR 유니버스가 시총 랭킹 없이 만들어졌는지 — True 면 캐시하지 않는다.
        self._kr_universe_partial = False

    # ---- 캐시 ----
    def clear_cache(self) -> None:
        with self._lock:
            self._bars.clear()
            self._lists.clear()
            self._symbols.clear()
            self._quotes.clear()
            self._names.clear()

    # ---- 원천 조회 ----
    def _daily(self, kind: str, symbol: str) -> pd.DataFrame:
        """일봉. **당일 1회만** 조회하고 날짜가 바뀔 때까지 재사용한다."""
        today = self._today_fn()
        key = (kind, symbol)
        with self._lock:
            hit = self._bars.get(key)
            if hit and hit[0] == today:
                return hit[1]
        df = self.kis_bars.daily_bars(kind, symbol, today - timedelta(days=_BARS_WINDOW_DAYS),
                                 today)
        if df is None:
            df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        with self._lock:
            self._bars[key] = (today, df)
        return df

    def symbols(self, kind: str) -> list[str]:
        """매수 화면 유니버스 — KR 시총 30, US S&P500 상위 30(SPEC §4.2)."""
        today = self._today_fn()
        with self._lock:
            hit = self._symbols.get(kind)
            if hit and hit[0] == today:
                return list(hit[1])
        if kind == "KR":
            syms = self._kr_universe()
        elif kind == "US":
            syms = self._us_universe()
        else:
            raise TradingError("MARKET_MISMATCH", f"알 수 없는 시장입니다: {kind}")
        # 시총 랭킹이 빠진 채 만들어진 KR 유니버스는 순서가 신뢰할 수 없다 — 캐시하지 않고
        # 다음 요청에서 다시 시도한다.
        if not (kind == "KR" and getattr(self, "_kr_universe_partial", False)):
            with self._lock:
                self._symbols[kind] = (today, syms)
        return list(syms)

    def _rank_rows(self, path: str, tr: str, params: dict, attempts: int = 1) -> list[dict]:
        """KIS 랭킹 1건 조회. 실패·빈 응답은 빈 목록으로 돌려준다.

        KIS 랭킹은 가끔 rt_cd=0 인데 output 이 비어 오거나(초당 호출 초과 등) 예외를 낸다.
        중요한 랭킹은 `attempts` 를 올려 재시도한다 — 한 번 실패한 결과가 하루치 유니버스로
        굳으면 목록 순서가 종일 망가진다.
        """
        for i in range(max(1, attempts)):
            try:
                j = self.kis_bars._get(path, tr, params)
                rows = list(j.get("output") or [])
                if rows:
                    return rows
            except Exception:
                pass
            if i + 1 < attempts:
                _time.sleep(0.4)
        return []

    @staticmethod
    def _is_derivative(name: str) -> bool:
        """ETF·레버리지·인버스 등 파생상품인가.

        거래량·등락률 랭킹 상위는 레버리지/인버스 ETF 가 점령한다. v2 는 '주식 초보'용
        모의투자라, 설명 없이 인버스2X 를 목록 앞에 놓는 건 도움이 아니라 함정이다.
        종목명으로 거르는 건 정밀하지 않지만, 국내 ETF 는 운용사 브랜드가 이름 앞에
        반드시 붙어서 실무적으로 충분히 잡힌다.
        """
        if not name:
            return False
        brands = ("KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO", "SOL ", "ACE ",
                  "PLUS ", "RISE ", "KOSEF", "TIMEFOLIO", "WOORI", "히어로즈", "마이다스")
        keywords = ("레버리지", "인버스", "선물", "ETN", "커버드콜", "혼합형")
        upper = name.upper()
        return (any(upper.startswith(b) for b in brands)
                or any(k in name for k in keywords))

    def _kr_universe(self) -> list[str]:
        """국내 유니버스 — **랭킹 3종의 합집합**.

        KIS 시총 랭킹은 한 번에 30행이 상한이고 연속조회가 없다(tr_cont 빈 값). 그래서
        "더 보기"를 시총만으로는 만들 수 없다. 성격이 다른 랭킹(거래량·등락률)을 합쳐
        넓히되, 시총 순서를 앞에 두어 첫 화면은 익숙한 대형주부터 보이게 한다.
        """
        from simcore.live.kis_client import _TR

        base = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": "0000",
                "fid_div_cls_code": "0"}
        # 시총 랭킹이 목록의 '골격'이다 — 이게 빠지면 첫 화면이 잡주로 채워진다. 재시도한다.
        mcap = self._rank_rows(
            "/uapi/domestic-stock/v1/ranking/market-cap", _TR[("rank_mcap", "KR")],
            dict(base, fid_cond_scr_div_code="20174", fid_trgt_cls_code="0",
                 fid_trgt_exls_cls_code="0", fid_input_price_1="",
                 fid_input_price_2="", fid_vol_cnt=""), attempts=3)
        batches = [
            mcap,
            self._rank_rows(
                "/uapi/domestic-stock/v1/quotations/volume-rank", "FHPST01710000",
                dict(base, fid_cond_scr_div_code="20171", fid_blng_cls_code="0",
                     fid_trgt_cls_code="111111111", fid_trgt_exls_cls_code="000000",
                     fid_input_price_1="", fid_input_price_2="", fid_vol_cnt="",
                     fid_input_date_1="")),
            self._rank_rows(
                "/uapi/domestic-stock/v1/ranking/fluctuation", "FHPST01700000",
                dict(base, fid_cond_scr_div_code="20170", fid_rank_sort_cls_code="0",
                     fid_input_cnt_1="0", fid_prc_cls_code="0", fid_rsfl_rate1="",
                     fid_rsfl_rate2="", fid_trgt_cls_code="0", fid_trgt_exls_cls_code="0",
                     fid_input_price_1="", fid_input_price_2="", fid_vol_cnt="")),
        ]
        syms: list[str] = []
        seen: set[str] = set()
        with self._lock:
            for rows in batches:
                for row in rows:
                    code = (row.get("mksc_shrn_iscd") or row.get("stck_shrn_iscd") or "").strip()
                    if not code or code in seen:
                        continue
                    name = (row.get("hts_kor_isnm") or "").strip()
                    if self._is_derivative(name):
                        continue        # 초보용 목록에 인버스·레버리지를 올리지 않는다
                    seen.add(code)
                    syms.append(code)
                    if name:
                        self._names[code] = name
        self._kr_universe_partial = not mcap
        if mcap:
            return syms
        # 골격(시총)이 없다 — 첫 화면이 잡주로 채워지지 않도록 대형주를 앞에 세운다.
        # ① v1 헬퍼로 한 번 더 시도 → ② 그래도 없으면 정적 대형주 목록.
        # 이 결과는 `symbols()` 가 캐시하지 않는다(일시적 실패가 하루를 망치면 안 된다).
        head: list[str] = []
        try:
            head = [c for c in self.kis_bars.market_cap_ranking(_UNIVERSE_MAX)
                    if c and c not in seen]
        except Exception:
            head = []
        if not head:
            head = [c for c in _universe.FALLBACK_KOSPI200 if c not in seen]
        return head + syms

    def _us_universe(self) -> list[str]:
        """미국 유니버스 — S&P 500 전체(약 500종목).

        v1 의 `universe.sp500` 은 pandas 기본 UA 로 위키백과를 긁는데 지금은 403 이라
        **내장 폴백 30종목**만 캐시돼 있었다. 브라우저 UA 를 주면 503종목 + 회사명까지
        받을 수 있다. v1 캐시 파일(`universe_sp500.csv`)은 건드리지 않는다 — v1 리플레이의
        유니버스가 조용히 바뀌면 과거 백테스트와 비교가 깨진다.
        """
        path = Path(self._cache_dir) / "universe_sp500_v2.csv"
        if path.exists():
            try:
                df = pd.read_csv(path, dtype=str)
                with self._lock:
                    for sym, nm in zip(df["symbol"], df.get("name", [])):
                        if isinstance(nm, str) and nm.strip():
                            self._names[sym] = nm.strip()
                return df["symbol"].tolist()
            except Exception:
                pass
        try:
            import io
            import urllib.request

            req = urllib.request.Request(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                headers={"User-Agent": _WIKI_UA})
            html = urllib.request.urlopen(req, timeout=30).read().decode()
            table = pd.read_html(io.StringIO(html))[0]
            syms = [str(x).replace(".", "-") for x in table["Symbol"].tolist()]
            names = [str(x) for x in table["Security"].tolist()]
            # 위키백과 표는 **알파벳순**이라 그대로 쓰면 첫 화면이 "3M, A. O. Smith" 가 된다.
            # 시총 상위 목록(FALLBACK_SP500)을 앞으로 당겨 익숙한 이름부터 보이게 한다.
            order = {s: i for i, s in enumerate(_universe.FALLBACK_SP500)}
            pairs = sorted(zip(syms, names),
                           key=lambda sn: (order.get(sn[0], len(order)), sn[0]))
            syms = [s for s, _ in pairs]
            names = [n for _, n in pairs]
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({"symbol": syms, "name": names}).to_csv(path, index=False)
            with self._lock:
                self._names.update(dict(zip(syms, names)))
            return syms
        except Exception:
            return list(_universe.sp500(self._cache_dir))

    def _name_of(self, symbol: str, kind: str) -> str:
        with self._lock:
            hit = self._names.get(symbol)
        return hit or _names.display_name(symbol, kind)

    def current_price(self, kind: str, symbol: str) -> tuple[float, bool]:
        """(현재가, stale). 실시간 실패 시 **마지막 일봉 종가**로 폴백하고 stale=True.

        자동매도는 stale 가격을 쓰면 안 되므로(SPEC §6.3) 판단은 호출부에 맡기고
        여기서는 사실만 알려준다."""
        key = (kind, symbol)
        with self._lock:
            hit = self._quotes.get(key)
        if hit and hit[0] > self._clock():
            if hit[1] is not None:
                return hit[1], hit[2]
            # 직전 실시간 조회가 실패했다 — 재시도하지 않고 바로 일봉 폴백으로 간다
        else:
            try:
                price = float(self.kis.current_price(kind, symbol))
                if price > 0:
                    with self._lock:
                        self._quotes[key] = (self._clock() + _QUOTE_TTL, price, False)
                    return price, False
            except Exception:
                with self._lock:
                    self._quotes[key] = (self._clock() + _QUOTE_FAIL_TTL, None, True)
        try:
            bars = self._daily(kind, symbol)
        except Exception:
            bars = None
        if bars is not None and len(bars) and float(bars["close"].iloc[-1]) > 0:
            return float(bars["close"].iloc[-1]), True
        raise TradingError("PRICE_UNAVAILABLE",
                           f"{symbol} 의 현재가를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.")

    # ---- 조립 ----
    def _build_info(self, kind: str, symbol: str) -> StockInfo:
        price, stale = self.current_price(kind, symbol)
        try:
            bars = self._daily(kind, symbol)
        except Exception:
            bars = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        closes = [float(v) for v in bars["close"].tolist()] if len(bars) else []
        volumes = [float(v) for v in bars["volume"].tolist()] if len(bars) else []
        today = self._today_fn()
        # 장중에는 마지막 봉이 '오늘'이라 전일 종가가 그 앞 봉이다. 마감 전/후를 구분해
        # 등락률 기준을 잘못 잡으면 화면이 0% 로 보인다.
        has_today = bool(len(bars)) and pd.Timestamp(bars.index[-1]).date() >= today
        prev_close = None
        if has_today and len(closes) >= 2:
            prev_close = closes[-2]
        elif not has_today and closes:
            prev_close = closes[-1]

        spark7 = closes[-7:]
        week_base = spark7[0] if spark7 else None
        volume = volumes[-1] if volumes else None
        avg20 = None
        if len(volumes) >= 2:
            recent = volumes[-20:]
            avg20 = sum(recent) / len(recent)

        hi = lo = None
        if len(bars):
            window = bars[bars.index >= pd.Timestamp(today - timedelta(days=365))]
            if not len(window):
                window = bars
            hi = round(float(window["high"].max()), 4)
            lo = round(float(window["low"].min()), 4)

        return StockInfo(
            symbol=symbol,
            name=self._name_of(symbol, kind),
            price=price,
            change_pct=_pct(price, prev_close) if prev_close else None,
            spark7=[round(c, 4) for c in spark7],
            week_change_pct=_pct(price, week_base) if week_base else None,
            volume=volume,
            volume_vs_avg=(round(volume / avg20, 3) if volume and avg20 else None),
            high_52w=hi,
            low_52w=lo,
            stale=stale,
        )

    def list_stocks(self, kind: str, offset: int = 0,
                    limit: int = _PAGE_SIZE) -> tuple[list[StockInfo], int]:
        """종목 리스트 한 페이지와 유니버스 전체 개수.

        상세(현재가·일봉)는 **요청한 구간만** 채운다 — S&P500 전체를 한 번에 채우면
        KIS 호출이 1,000회라 첫 화면이 몇 분 걸린다. 비용이 '보이는 만큼'에 비례하게 둔다.
        페이지별 60초 TTL 캐시, 한 종목이 실패해도 목록 전체를 버리지 않는다.
        """
        universe = self.symbols(kind)
        total = len(universe)
        offset = max(0, int(offset))
        limit = max(1, int(limit))
        symbols = universe[offset:offset + limit]
        cache_key = f"{kind}:{offset}:{limit}"
        now = self._clock()
        with self._lock:
            hit = self._lists.get(cache_key)
            if hit and now - hit[0] < _LIST_TTL_SEC:
                return list(hit[1]), total
        # 종목당 현재가+일봉 2회를 순차로 돌면 30종목에 분 단위가 걸린다(첫 로드가 특히).
        # KisClient 의 레이트리미터가 초당 호출을 제한하므로 병렬로 던져도 안전하다.
        # 순서는 랭킹 순서를 유지해야 하므로 인덱스로 되돌린다.
        results: dict[int, StockInfo] = {}
        with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
            futures = {pool.submit(self._build_info, kind, sym): i
                       for i, sym in enumerate(symbols)}
            for fut in as_completed(futures):
                try:
                    results[futures[fut]] = fut.result()
                except Exception:
                    continue      # 개별 종목 실패는 화면 전체를 막을 이유가 못 된다
        out = [results[i] for i in sorted(results)]
        with self._lock:
            self._lists[cache_key] = (self._clock(), out)
        return list(out), total

    def get_stock(self, kind: str, symbol: str) -> StockDetail:
        """단일 종목 + 최근 30일 일봉(SPEC §7 `/market/{kind}/stocks/{symbol}`)."""
        info = self._build_info(kind, symbol)
        try:
            bars = self._daily(kind, symbol)
        except Exception:
            bars = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        rows: list[dict[str, Any]] = []
        for ts, r in bars.tail(30).iterrows():
            rows.append({"date": pd.Timestamp(ts).date().isoformat(),
                         "open": float(r["open"]), "high": float(r["high"]),
                         "low": float(r["low"]), "close": float(r["close"]),
                         "volume": float(r["volume"])})
        return StockDetail(info=info, bars=rows, kind=kind,
                           currency="KRW" if kind == "KR" else "USD")


# ---------------------------------------------------------------- 모듈 기본 인스턴스
# 라우터·스케줄러는 `market.list_stocks(...)` 처럼 모듈 함수를 쓰고, 테스트는
# `configure(FakeKis())` 로 갈아끼운다. 전역 하나로 캐시를 공유하는 게 목적이다.

_default: MarketService | None = None


def configure(kis, **kwargs) -> MarketService:
    """기본 서비스를 (재)설정하고 반환한다. 테스트에서 가짜 KIS 를 주입하는 통로."""
    global _default
    _default = MarketService(kis, **kwargs)
    return _default


def init_from_settings(session_factory, settings: V2Settings) -> MarketService:
    return configure(make_kis_client(session_factory, settings),
                     kis_bars=make_bars_client(session_factory, settings))


def service() -> MarketService:
    if _default is None:
        raise RuntimeError("market.configure() 또는 init_from_settings() 를 먼저 호출해야 합니다.")
    return _default


def clear_cache() -> None:
    if _default is not None:
        _default.clear_cache()


def list_stocks(kind: str, offset: int = 0,
                limit: int = _PAGE_SIZE) -> tuple[list[StockInfo], int]:
    return service().list_stocks(kind, offset, limit)


def page_size() -> int:
    return _PAGE_SIZE


def get_stock(kind: str, symbol: str) -> StockDetail:
    return service().get_stock(kind, symbol)


def current_price(kind: str, symbol: str) -> tuple[float, bool]:
    return service().current_price(kind, symbol)
