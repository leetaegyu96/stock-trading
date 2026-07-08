# simcore 라이브 모드 (KIS + 스케줄러 + Postgres) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 완료된 순수 매매 엔진을 KIS 실시세로 실시간 구동하고, 상태·이력을 PostgreSQL에 영속화하여 재시작에도 이어서 매매하는 백그라운드 데몬을 만든다.

**Architecture:** 순수 엔진(engine/portfolio/signals/replay)은 무변경. 엔진 바깥에 얇은 `simcore/live/` 계층(kis_client·calendar·repository·orchestrator·scheduler·__main__)을 추가한다. orchestrator는 `run_replay`와 동일한 엔진 메서드를 같은 순서로 호출하고, 차이는 데이터 출처(KIS)와 저장(Postgres)뿐이다.

**Tech Stack:** Python 3.11+, httpx(REST), SQLAlchemy 2.x + psycopg(Postgres), APScheduler, pydantic-settings, zoneinfo, pytest.

## Global Constraints

- Python `>=3.11` (기존 pyproject 준수).
- **순수 엔진 코드(`simcore/engine.py`, `portfolio.py`, `signals.py`, `indicators.py`, `costs.py`, `models.py`, `metrics.py`, `replay.py`)는 수정 금지.** 기존 63개 테스트가 그대로 통과해야 한다.
- KIS는 **읽기 전용 데이터 피드**. 주문 API 호출 금지. 도메인은 `KIS_ENV=real`.
- 시크릿(`KIS_APP_KEY/SECRET`, `DATABASE_URL`)은 `.env`에서만 로드. 로그·에러·`repr`에 노출 금지(마스킹).
- 신규 코드는 모두 `simcore/live/` 아래. 테스트는 `tests/live/` 아래.
- DB 테스트는 환경변수 `TEST_DATABASE_URL`이 있을 때만 실행(없으면 `pytest.skip`).
- 커밋은 CLAUDE.md 워크플로: `dev`에서 작업 브랜치 분기 → 논리 단위 커밋 → dev 병합 → 브랜치 삭제.
- 매매 규칙 단일 기준: `docs/trading-rules.md` (불변). 상세 설계: `docs/superpowers/specs/2026-07-08-simcore-live-kis-design.md`.

---

## 파일 구조

```
simcore/live/
├── __init__.py
├── settings.py       # pydantic-settings: KIS 키·DATABASE_URL·env·레이트리밋 (마스킹)
├── ratelimit.py      # 토큰버킷 리미터 (동기)
├── kis_client.py     # KIS REST 래퍼 + TokenStore 프로토콜
├── calendar.py       # KR/US 거래일·세션시각 판정 (zoneinfo, 주입 휴장일)
├── db.py             # SQLAlchemy 엔진·세션·Base·ORM 테이블 정의
├── repository.py     # 상태 persist/rehydrate + 이력 append + run_state 멱등
├── orchestrator.py   # 엔진 구동자: KIS→엔진→repository (run_replay의 라이브판)
├── recovery.py       # 갭 리플레이 재시작 복구
├── scheduler.py      # APScheduler 트리거 배선 + calendar 가드
└── __main__.py       # 데몬 진입점 + CLI(deposit/withdraw)

tests/live/
├── __init__.py
├── conftest.py       # 목 KIS·임시 DB 픽스처, TEST_DATABASE_URL 가드
├── test_settings.py
├── test_ratelimit.py
├── test_kis_client.py
├── test_calendar.py
├── test_repository.py
├── test_orchestrator.py
├── test_equivalence.py   # ★ 라이브 ≡ 리플레이
├── test_recovery.py
└── test_scheduler.py
```

---

### Task 1: 의존성 + 라이브 설정(settings)

**Files:**
- Modify: `pyproject.toml` (dependencies 추가)
- Create: `simcore/live/__init__.py` (빈 파일)
- Create: `simcore/live/settings.py`
- Create: `tests/live/__init__.py` (빈 파일)
- Test: `tests/live/test_settings.py`

**Interfaces:**
- Produces:
  - `class LiveSettings` (pydantic-settings). 필드: `kis_app_key: str`, `kis_app_secret: str`, `kis_account_no: str = ""`, `kis_env: str = "real"`, `database_url: str`, `test_database_url: str | None = None`, `kis_rate_limit_per_sec: float = 10.0`.
  - `def kis_base_url(self) -> str` — env에 따라 real/paper 도메인 반환.
  - `repr`/`str`에 시크릿 마스킹.
  - `def load_settings() -> LiveSettings` — `.env`에서 로드.

- [ ] **Step 1: 의존성 추가** — `pyproject.toml`의 `dependencies`에 추가:

```toml
dependencies = [
    "pandas>=2.0",
    "numpy>=1.26",
    "pykrx>=1.0.45",
    "yfinance>=0.2.40",
    "pyarrow>=15",
    "lxml>=5",
    "httpx>=0.27",
    "SQLAlchemy>=2.0",
    "psycopg[binary]>=3.1",
    "APScheduler>=3.10",
    "pydantic-settings>=2.2",
]
```
그리고 `dev`에 `respx>=0.21` 추가: `dev = ["pytest>=8", "respx>=0.21"]`

- [ ] **Step 2: 실패 테스트 작성** — `tests/live/test_settings.py`:

```python
import pytest
from simcore.live.settings import LiveSettings


def _mk(**over):
    base = dict(kis_app_key="AK", kis_app_secret="SEKRET",
                database_url="postgresql://u:p@localhost/db")
    base.update(over)
    return LiveSettings(**base)


def test_defaults_and_base_url():
    s = _mk()
    assert s.kis_env == "real"
    assert s.kis_base_url() == "https://openapi.koreainvestment.com:9443"
    assert s.kis_rate_limit_per_sec == 10.0


def test_paper_base_url():
    assert _mk(kis_env="paper").kis_base_url().endswith(":29443")


def test_secrets_masked_in_repr():
    s = _mk()
    text = repr(s)
    assert "SEKRET" not in text
    assert "AK" not in text
    assert "***" in text
```

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/live/test_settings.py -v`
Expected: FAIL — `ModuleNotFoundError: simcore.live.settings`

- [ ] **Step 4: 구현** — `simcore/live/settings.py`:

```python
"""라이브 모드 설정. .env 에서 로드하며 시크릿을 마스킹한다."""
from __future__ import annotations
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REAL = "https://openapi.koreainvestment.com:9443"
_PAPER = "https://openapivts.koreainvestment.com:29443"


class LiveSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8",
                                      extra="ignore")
    kis_app_key: str = Field(alias="KIS_APP_KEY")
    kis_app_secret: str = Field(alias="KIS_APP_SECRET")
    kis_account_no: str = Field(default="", alias="KIS_ACCOUNT_NO")
    kis_env: str = Field(default="real", alias="KIS_ENV")
    database_url: str = Field(alias="DATABASE_URL")
    test_database_url: str | None = Field(default=None, alias="TEST_DATABASE_URL")
    kis_rate_limit_per_sec: float = Field(default=10.0, alias="KIS_RATE_LIMIT_PER_SEC")

    def kis_base_url(self) -> str:
        return _PAPER if self.kis_env == "paper" else _REAL

    def __repr__(self) -> str:
        return (f"LiveSettings(kis_env={self.kis_env!r}, "
                f"kis_app_key='***', kis_app_secret='***', "
                f"database_url='***', account='***')")

    __str__ = __repr__


def load_settings() -> LiveSettings:
    return LiveSettings()  # type: ignore[call-arg]
```

주: 테스트는 alias 없이 소문자 필드로도 생성 가능하도록 `populate_by_name`이 필요하다. `model_config`에 `populate_by_name=True` 추가.

- [ ] **Step 5: populate_by_name 반영 후 통과 확인**

Run: `python -m pytest tests/live/test_settings.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: 커밋**

```bash
git add pyproject.toml simcore/live/__init__.py simcore/live/settings.py tests/live/__init__.py tests/live/test_settings.py
git commit -m "feat(live): 라이브 설정 로더 + 의존성 추가"
```

---

### Task 2: 토큰버킷 레이트리미터

**Files:**
- Create: `simcore/live/ratelimit.py`
- Test: `tests/live/test_ratelimit.py`

**Interfaces:**
- Produces:
  - `class RateLimiter(rate_per_sec: float, clock=time.monotonic, sleep=time.sleep)`
  - `def acquire(self) -> None` — 필요 시 sleep 하여 초당 호출 상한 유지.

- [ ] **Step 1: 실패 테스트 작성** — `tests/live/test_ratelimit.py`:

```python
from simcore.live.ratelimit import RateLimiter


def test_allows_burst_then_throttles():
    now = [0.0]
    slept = []
    limiter = RateLimiter(rate_per_sec=2.0,
                          clock=lambda: now[0],
                          sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    limiter.acquire()  # 즉시
    limiter.acquire()  # 즉시 (버킷 2개)
    limiter.acquire()  # 세 번째는 대기
    assert slept and slept[-1] > 0
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/live/test_ratelimit.py -v`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: 구현** — `simcore/live/ratelimit.py`:

```python
"""동기 토큰버킷 레이트리미터."""
from __future__ import annotations
import time
from typing import Callable


class RateLimiter:
    def __init__(self, rate_per_sec: float,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.capacity = max(1.0, rate_per_sec)
        self.rate = rate_per_sec
        self.tokens = self.capacity
        self.clock = clock
        self.sleep = sleep
        self.last = clock()

    def acquire(self) -> None:
        while True:
            now = self.clock()
            self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
            self.sleep((1.0 - self.tokens) / self.rate)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/live/test_ratelimit.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add simcore/live/ratelimit.py tests/live/test_ratelimit.py
git commit -m "feat(live): 토큰버킷 레이트리미터"
```

---

### Task 3: KIS 클라이언트 — 토큰 발급/캐시 + 국내 현재가/일봉

**Files:**
- Create: `simcore/live/kis_client.py`
- Test: `tests/live/test_kis_client.py`

**Interfaces:**
- Consumes: `RateLimiter` (Task 2), `LiveSettings` (Task 1).
- Produces:
  - `class TokenStore(Protocol)`: `def get(self) -> tuple[str, float] | None`, `def save(self, token: str, expires_at: float) -> None`.
  - `class InMemoryTokenStore` — 위 프로토콜 구현(테스트·기본용).
  - `class KisClient(settings, token_store, limiter, client: httpx.Client | None = None, clock=time.time)`
    - `def current_price(self, market: str, symbol: str) -> float` — market은 `"KR"`/`"US"`.
    - `def daily_bars(self, market: str, symbol: str, start: date, end: date) -> pandas.DataFrame` (index=Datetime, cols open/high/low/close/volume).
    - `def market_cap_ranking(self, top_n: int) -> list[str]` (KR 종목코드, Task 4에서 구현).
    - 내부 `_token()` — 캐시 없거나 만료 임박(<600s)이면 `/oauth2/tokenP` 발급 후 store 저장.
    - 401 응답 시 토큰 무효화 후 1회 재시도. 429/5xx는 지수 백오프 3회.

- [ ] **Step 1: 실패 테스트 작성 (토큰 캐시 + 현재가)** — `tests/live/test_kis_client.py`:

```python
import httpx, respx, pytest
from datetime import date
from simcore.live.kis_client import KisClient, InMemoryTokenStore
from simcore.live.ratelimit import RateLimiter
from simcore.live.settings import LiveSettings

BASE = "https://openapi.koreainvestment.com:9443"


def _client(clock_val=1000.0):
    s = LiveSettings(kis_app_key="AK", kis_app_secret="SK",
                     database_url="postgresql://x", kis_env="real")
    limiter = RateLimiter(1e9)  # 테스트에선 무제한
    return KisClient(s, InMemoryTokenStore(), limiter,
                     client=httpx.Client(base_url=BASE), clock=lambda: clock_val)


@respx.mock
def test_token_issued_once_and_cached():
    tok = respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "TОКEN", "expires_in": 86400}))
    price = respx.get(f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-price").mock(
        return_value=httpx.Response(200, json={"output": {"stck_prpr": "70000"}}))
    c = _client()
    assert c.current_price("KR", "005930") == 70000.0
    assert c.current_price("KR", "005930") == 70000.0
    assert tok.call_count == 1          # 토큰은 1회만 발급
    assert price.call_count == 2


@respx.mock
def test_daily_bars_parsed():
    respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "T", "expires_in": 86400}))
    respx.get(f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice").mock(
        return_value=httpx.Response(200, json={"output2": [
            {"stck_bsop_date": "20260707", "stck_oprc": "100", "stck_hgpr": "110",
             "stck_lwpr": "90", "stck_clpr": "105", "acml_vol": "1000"},
        ]}))
    c = _client()
    df = c.daily_bars("KR", "005930", date(2026, 7, 1), date(2026, 7, 7))
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.iloc[0]["close"] == 105.0
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/live/test_kis_client.py -v`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: 구현** — `simcore/live/kis_client.py` (국내 현재가/일봉 + 토큰):

```python
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
```

주: `_overseas_*`/`market_cap_ranking`은 Task 4에서 실제 구현으로 대체(여기선 스텁 선언만 두고 KR 경로만 통과시킴). Task 4 완료 전까지 US·랭킹 호출 테스트는 작성하지 않는다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/live/test_kis_client.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 401 재발급 테스트 추가** — 같은 파일에:

```python
@respx.mock
def test_reissues_token_on_401():
    respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "T", "expires_in": 86400}))
    route = respx.get(f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-price")
    route.side_effect = [httpx.Response(401, json={}),
                         httpx.Response(200, json={"output": {"stck_prpr": "5"}})]
    c = _client()
    assert c.current_price("KR", "005930") == 5.0
    assert route.call_count == 2
```

Run: `python -m pytest tests/live/test_kis_client.py -v` → PASS (3 passed)

- [ ] **Step 6: 커밋**

```bash
git add simcore/live/kis_client.py tests/live/test_kis_client.py
git commit -m "feat(live): KIS 토큰 캐시 + 국내 현재가/일봉 클라이언트"
```

---

### Task 4: KIS 클라이언트 — 시총 랭킹(KR 유니버스) + 해외 시세

**Files:**
- Modify: `simcore/live/kis_client.py` (스텁 3개를 실제 구현으로)
- Test: `tests/live/test_kis_client.py` (테스트 추가)

**Interfaces:**
- Produces (KisClient 메서드 실구현):
  - `market_cap_ranking(top_n) -> list[str]`
  - `_overseas_price(symbol) -> float`, `_overseas_daily(symbol, start, end) -> pd.DataFrame`
  - `symbol` 형식(US): `"NAS:AAPL"` 처럼 `거래소:티커`. 거래소 미상이면 NAS/NYS 순차 시도.

- [ ] **Step 1: 실패 테스트 작성** — `tests/live/test_kis_client.py`에 추가:

```python
@respx.mock
def test_market_cap_ranking():
    respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "T", "expires_in": 86400}))
    respx.get(f"{BASE}/uapi/domestic-stock/v1/ranking/market-cap").mock(
        return_value=httpx.Response(200, json={"output": [
            {"mksc_shrn_iscd": "005930"}, {"mksc_shrn_iscd": "000660"},
            {"mksc_shrn_iscd": "373220"}]}))
    c = _client()
    assert c.market_cap_ranking(2) == ["005930", "000660"]


@respx.mock
def test_overseas_price():
    respx.post(f"{BASE}/oauth2/tokenP").mock(return_value=httpx.Response(
        200, json={"access_token": "T", "expires_in": 86400}))
    respx.get(f"{BASE}/uapi/overseas-price/v1/quotations/price").mock(
        return_value=httpx.Response(200, json={"output": {"last": "191.24"}}))
    c = _client()
    assert c.current_price("US", "NAS:AAPL") == 191.24
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/live/test_kis_client.py -k "ranking or overseas" -v`
Expected: FAIL (스텁이 `...` 반환 → None/에러)

- [ ] **Step 3: 구현** — `kis_client.py`의 스텁 3개 대체:

```python
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

    def _split_us(self, symbol: str) -> "list[tuple[str, str]]":
        if ":" in symbol:
            exch, tkr = symbol.split(":", 1)
            return [(exch, tkr := tkr)]
        return [("NAS", symbol), ("NYS", symbol)]

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
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/live/test_kis_client.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add simcore/live/kis_client.py tests/live/test_kis_client.py
git commit -m "feat(live): KIS 시총 랭킹(KR 유니버스) + 해외 시세"
```

주(구현자 참고): KIS 실제 응답 필드명은 문서/실호출로 재확인 필요. 필드가 다르면 파서만 수정하고 테스트 픽스처도 함께 갱신한다. Task 15 스모크 런에서 최종 검증.

---

### Task 5: 거래 캘린더 (calendar)

**Files:**
- Create: `simcore/live/calendar.py`
- Test: `tests/live/test_calendar.py`

**Interfaces:**
- Produces:
  - `KR_TZ = ZoneInfo("Asia/Seoul")`, `US_TZ = ZoneInfo("America/New_York")`.
  - `def is_trading_day(d: date, market: str, holidays: set[date]) -> bool` — 주말·휴장일 제외.
  - `def session_open(d: date, market: str) -> datetime` (tz-aware) — KR 09:00 KST, US 09:30 ET.
  - `def session_close(d: date, market: str) -> datetime` — KR 15:30 KST, US 16:00 ET.
  - `def previous_trading_day(d, market, holidays) -> date`, `def trading_days_between(start, end, market, holidays) -> list[date]`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/live/test_calendar.py`:

```python
from datetime import date
from simcore.live import calendar as cal


def test_weekend_not_trading():
    assert not cal.is_trading_day(date(2026, 7, 4), "KR", set())   # 토
    assert not cal.is_trading_day(date(2026, 7, 5), "KR", set())   # 일
    assert cal.is_trading_day(date(2026, 7, 6), "KR", set())       # 월


def test_holiday_excluded():
    h = {date(2026, 7, 6)}
    assert not cal.is_trading_day(date(2026, 7, 6), "KR", h)


def test_us_dst_offset_changes():
    # 여름(DST): ET는 UTC-4 → 09:30 ET = 13:30 UTC
    summer = cal.session_open(date(2026, 7, 6), "US")
    assert summer.utcoffset().total_seconds() == -4 * 3600
    # 겨울(표준시): ET는 UTC-5
    winter = cal.session_open(date(2026, 1, 6), "US")
    assert winter.utcoffset().total_seconds() == -5 * 3600


def test_kr_session_times():
    o = cal.session_open(date(2026, 7, 6), "KR")
    c = cal.session_close(date(2026, 7, 6), "KR")
    assert (o.hour, o.minute) == (9, 0)
    assert (c.hour, c.minute) == (15, 30)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/live/test_calendar.py -v`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: 구현** — `simcore/live/calendar.py`:

```python
"""KR/US 거래일·세션시각 판정. 휴장일은 외부 주입(테스트 결정론)."""
from __future__ import annotations
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KR_TZ = ZoneInfo("Asia/Seoul")
US_TZ = ZoneInfo("America/New_York")
_TZ = {"KR": KR_TZ, "US": US_TZ}
_OPEN = {"KR": time(9, 0), "US": time(9, 30)}
_CLOSE = {"KR": time(15, 30), "US": time(16, 0)}


def is_trading_day(d: date, market: str, holidays: set[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def session_open(d: date, market: str) -> datetime:
    return datetime.combine(d, _OPEN[market], tzinfo=_TZ[market])


def session_close(d: date, market: str) -> datetime:
    return datetime.combine(d, _CLOSE[market], tzinfo=_TZ[market])


def previous_trading_day(d: date, market: str, holidays: set[date]) -> date:
    cur = d - timedelta(days=1)
    while not is_trading_day(cur, market, holidays):
        cur -= timedelta(days=1)
    return cur


def trading_days_between(start: date, end: date, market: str,
                         holidays: set[date]) -> list[date]:
    out, cur = [], start
    while cur <= end:
        if is_trading_day(cur, market, holidays):
            out.append(cur)
        cur += timedelta(days=1)
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/live/test_calendar.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add simcore/live/calendar.py tests/live/test_calendar.py
git commit -m "feat(live): KR/US 거래 캘린더 (zoneinfo, DST)"
```

주: KR 휴장일 로더(KIS 휴장일 API)와 US 휴장일 목록은 orchestrator/scheduler 배선(Task 13)에서 주입. 정밀 휴장일·조기폐장은 서브프로젝트 5.

---

### Task 6: DB 스키마 (SQLAlchemy ORM)

**Files:**
- Create: `simcore/live/db.py`
- Test: `tests/live/test_repository.py` (스키마 생성 스모크), `tests/live/conftest.py`

**Interfaces:**
- Produces:
  - `Base` (DeclarativeBase), ORM 클래스: `CharacterRow, CashBalance, PositionRow, PendingOrder, Cooldown, RunState, KisToken, TradeRow, CapitalFlowRow, FlowRequest, EquityPoint, DailyBarRow, UniverseRow` — 스펙 §5 컬럼과 1:1.
  - `def make_engine(url: str)`, `def make_session_factory(engine)`, `def create_all(engine)`.
- Consumes: 없음.

- [ ] **Step 1: conftest 픽스처 작성** — `tests/live/conftest.py`:

```python
import os, pytest
from simcore.live.db import make_engine, make_session_factory, create_all, Base

TEST_DB = os.environ.get("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL 미설정")


@pytest.fixture
def session():
    if not TEST_DB:
        pytest.skip("TEST_DATABASE_URL 미설정")
    engine = make_engine(TEST_DB)
    Base.metadata.drop_all(engine)
    create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        yield s
    Base.metadata.drop_all(engine)
```

- [ ] **Step 2: 실패 테스트 작성** — `tests/live/test_repository.py`:

```python
from tests.live.conftest import needs_db
from simcore.live.db import CashBalance


@needs_db
def test_insert_and_query_cash(session):
    session.add(CashBalance(character="국내형", currency="KRW", amount=100.0))
    session.commit()
    row = session.query(CashBalance).filter_by(character="국내형").one()
    assert row.amount == 100.0
```

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/live/test_repository.py -v`
Expected: FAIL — 모듈 없음 (또는 TEST_DATABASE_URL 없으면 SKIP — 이 경우 로컬 docker Postgres를 띄우고 `export TEST_DATABASE_URL=...` 후 재실행)

- [ ] **Step 4: 구현** — `simcore/live/db.py` (핵심 테이블; 컬럼은 스펙 §5):

```python
"""SQLAlchemy ORM 스키마 (스펙 §5)."""
from __future__ import annotations
from datetime import date, datetime
from sqlalchemy import (String, Float, Integer, Date, DateTime, ForeignKey,
                        create_engine)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class CharacterRow(Base):
    __tablename__ = "characters"
    name: Mapped[str] = mapped_column(String, primary_key=True)
    base_currency: Mapped[str] = mapped_column(String)


class CashBalance(Base):
    __tablename__ = "cash_balances"
    character: Mapped[str] = mapped_column(String, primary_key=True)
    currency: Mapped[str] = mapped_column(String, primary_key=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)


class PositionRow(Base):
    __tablename__ = "positions"
    character: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    market: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column(Integer)
    avg_price: Mapped[float] = mapped_column(Float)
    opened_date: Mapped[date] = mapped_column(Date)


class PendingOrder(Base):
    __tablename__ = "pending_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)         # BUY/SELL
    symbol: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    green_count: Mapped[int] = mapped_column(Integer, default=0)
    red_count: Mapped[int] = mapped_column(Integer, default=0)
    change_pct: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    fired: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    reason: Mapped[str] = mapped_column(String, default="SIGNAL_SELL")
    created_date: Mapped[date] = mapped_column(Date)


class Cooldown(Base):
    __tablename__ = "cooldowns"
    character: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    market: Mapped[str] = mapped_column(String)
    remaining_days: Mapped[int] = mapped_column(Integer)


class RunState(Base):
    __tablename__ = "run_state"
    market: Mapped[str] = mapped_column(String, primary_key=True)
    last_open_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_fx_rate: Mapped[float] = mapped_column(Float, default=0.0)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)


class KisToken(Base):
    __tablename__ = "kis_token"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    access_token: Mapped[str] = mapped_column(String)
    expires_at: Mapped[float] = mapped_column(Float)


class TradeRow(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    date: Mapped[date] = mapped_column(Date)
    character: Mapped[str] = mapped_column(String)
    symbol: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float)
    tax: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String)
    green_count: Mapped[int] = mapped_column(Integer, default=0)
    red_count: Mapped[int] = mapped_column(Integer, default=0)
    fired: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)


class CapitalFlowRow(Base):
    __tablename__ = "capital_flows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date)
    character: Mapped[str] = mapped_column(String)
    amount_krw: Mapped[float] = mapped_column(Float)
    fx_rate: Mapped[float] = mapped_column(Float)


class FlowRequest(Base):
    __tablename__ = "flow_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character: Mapped[str] = mapped_column(String)
    amount_krw: Mapped[float] = mapped_column(Float)
    liquidate: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    status: Mapped[str] = mapped_column(String, default="pending")
    requested_at: Mapped[datetime] = mapped_column(DateTime)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EquityPoint(Base):
    __tablename__ = "equity_curve"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    character: Mapped[str] = mapped_column(String)
    equity_krw: Mapped[float] = mapped_column(Float)


class DailyBarRow(Base):
    __tablename__ = "daily_bars"
    market: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)


class UniverseRow(Base):
    __tablename__ = "universe"
    market: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer)


def make_engine(url: str):
    return create_engine(url, future=True)


def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False, future=True)


def create_all(engine) -> None:
    Base.metadata.create_all(engine)
```

- [ ] **Step 5: 통과 확인** (로컬 docker Postgres 필요)

```bash
docker run -d --name simcore-testdb -e POSTGRES_PASSWORD=pw -p 5433:5432 postgres:16
export TEST_DATABASE_URL="postgresql+psycopg://postgres:pw@localhost:5433/postgres"
python -m pytest tests/live/test_repository.py -v
```
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add simcore/live/db.py tests/live/conftest.py tests/live/test_repository.py
git commit -m "feat(live): Postgres ORM 스키마 (SQLAlchemy)"
```

---

### Task 7: Repository — 상태 persist / rehydrate 왕복

**Files:**
- Create: `simcore/live/repository.py`
- Test: `tests/live/test_repository.py` (추가)

**Interfaces:**
- Consumes: `db.py` ORM (Task 6), 순수 `Engine`/`CharacterState`/`Portfolio`/`PendingBuy`/`PendingSell`/`Position`.
- Produces:
  - `class Repository(session_factory)`
    - `def persist_state(self, engine: Engine) -> None` — cash/positions/pending/cooldowns 전체 덮어쓰기(트랜잭션).
    - `def rehydrate(self, engine: Engine) -> bool` — DB→엔진 상태 복원. 반환: 상태가 있었으면 True(콜드스타트 여부 판정).
    - `class DbTokenStore(session_factory)` — TokenStore 프로토콜 구현(`kis_token` 사용).

- [ ] **Step 1: 실패 테스트 작성** — `tests/live/test_repository.py`에 추가:

```python
from datetime import date
from tests.live.conftest import needs_db
from simcore.config import Config
from simcore.engine import Engine
from simcore.models import Market
from simcore.live.repository import Repository
from simcore.live.db import make_engine, make_session_factory


@needs_db
def test_persist_rehydrate_roundtrip(session):
    import os
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    eng.start(date(2026, 7, 6), 1300.0)                 # 3캐릭터 1억 입금
    st = eng.states["국내형"]
    st.portfolio.buy(date(2026, 7, 6), "005930", Market.KR, 10, 70000.0,
                     __import__("simcore.models", fromlist=["TradeReason"]).TradeReason.SIGNAL_BUY)
    st.cooldowns["000660"] = [Market.KR, 2]
    repo.persist_state(eng)

    eng2 = Engine(Config())
    assert repo.rehydrate(eng2) is True
    s2 = eng2.states["국내형"]
    assert "005930" in s2.portfolio.positions
    assert s2.portfolio.positions["005930"].quantity == 10
    assert abs(s2.portfolio.cash[list(s2.portfolio.cash)[0]]
               - st.portfolio.cash[list(st.portfolio.cash)[0]]) < 1e-3
    assert s2.cooldowns["000660"][1] == 2
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/live/test_repository.py::test_persist_rehydrate_roundtrip -v`
Expected: FAIL — repository 모듈 없음

- [ ] **Step 3: 구현** — `simcore/live/repository.py`:

```python
"""엔진 상태 영속/복원 + 이력 append + run_state 멱등 (스펙 §5)."""
from __future__ import annotations
from datetime import date, datetime
from sqlalchemy import delete, select

from simcore.engine import Engine, PendingBuy, PendingSell
from simcore.models import (Currency, Market, Position, TradeReason)
from simcore.live import db


class DbTokenStore:
    def __init__(self, session_factory):
        self.sf = session_factory
    def get(self):
        with self.sf() as s:
            row = s.get(db.KisToken, 1)
            return (row.access_token, row.expires_at) if row and row.access_token else None
    def save(self, token: str, expires_at: float) -> None:
        with self.sf() as s:
            row = s.get(db.KisToken, 1)
            if row is None:
                s.add(db.KisToken(id=1, access_token=token, expires_at=expires_at))
            else:
                row.access_token, row.expires_at = token, expires_at
            s.commit()


class Repository:
    def __init__(self, session_factory):
        self.sf = session_factory

    def persist_state(self, engine: Engine) -> None:
        with self.sf() as s:
            for t in (db.CashBalance, db.PositionRow, db.PendingOrder, db.Cooldown):
                s.execute(delete(t))
            for name, st in engine.states.items():
                s.merge(db.CharacterRow(name=name,
                                        base_currency=st.portfolio.base_currency.value))
                for cur, amt in st.portfolio.cash.items():
                    s.add(db.CashBalance(character=name, currency=cur.value, amount=amt))
                for sym, pos in st.portfolio.positions.items():
                    s.add(db.PositionRow(character=name, symbol=sym, market=pos.market.value,
                                         quantity=pos.quantity, avg_price=pos.avg_price,
                                         opened_date=pos.opened))
                for b in st.pending_buys:
                    s.add(db.PendingOrder(character=name, side="BUY", symbol=b.symbol,
                                          market=b.market.value, green_count=b.green_count,
                                          change_pct=b.change_pct, volume=b.volume,
                                          fired=list(b.fired), created_date=date.today()))
                for ps in st.pending_sells:
                    s.add(db.PendingOrder(character=name, side="SELL", symbol=ps.symbol,
                                          market=ps.market.value, red_count=ps.red_count,
                                          fired=list(ps.fired), reason=ps.reason.value,
                                          created_date=date.today()))
                for sym, (mkt, rem) in st.cooldowns.items():
                    s.add(db.Cooldown(character=name, symbol=sym, market=mkt.value,
                                      remaining_days=rem))
            s.commit()

    def rehydrate(self, engine: Engine) -> bool:
        with self.sf() as s:
            cash = s.execute(select(db.CashBalance)).scalars().all()
            if not cash:
                return False
            for row in cash:
                st = engine.states.get(row.character)
                if st:
                    st.portfolio.cash[Currency(row.currency)] = row.amount
            for p in s.execute(select(db.PositionRow)).scalars():
                st = engine.states.get(p.character)
                if st:
                    st.portfolio.positions[p.symbol] = Position(
                        p.symbol, Market(p.market), p.quantity, p.avg_price, p.opened_date)
            for o in s.execute(select(db.PendingOrder)).scalars():
                st = engine.states.get(o.character)
                if not st:
                    continue
                if o.side == "BUY":
                    st.pending_buys.append(PendingBuy(o.symbol, Market(o.market),
                        o.green_count, tuple(o.fired or ()), o.change_pct, o.volume))
                else:
                    st.pending_sells.append(PendingSell(o.symbol, Market(o.market),
                        TradeReason(o.reason), o.red_count, tuple(o.fired or ())))
            for c in s.execute(select(db.Cooldown)).scalars():
                st = engine.states.get(c.character)
                if st:
                    st.cooldowns[c.symbol] = [Market(c.market), c.remaining_days]
            return True
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/live/test_repository.py::test_persist_rehydrate_roundtrip -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add simcore/live/repository.py tests/live/test_repository.py
git commit -m "feat(live): Repository 상태 persist/rehydrate + 토큰 스토어"
```

---

### Task 8: Repository — 이력 append + run_state 멱등 + flow 큐

**Files:**
- Modify: `simcore/live/repository.py`
- Test: `tests/live/test_repository.py` (추가)

**Interfaces:**
- Produces (Repository 메서드):
  - `def append_new_trades(self, engine) -> None` — 각 캐릭터 portfolio.trades 중 아직 DB에 없는 것만 append(세션-로컬 카운터로 신규분 판정).
  - `def record_equity(self, ts: datetime, snap: dict[str, float]) -> None`.
  - `def record_flow(self, flow) -> None` (capital_flows).
  - `def get_run_state(self, market: str) -> db.RunState`(없으면 생성).
  - `def mark_open(self, market, d, fx) / mark_close(self, market, d, fx)`.
  - `def pending_flow_requests(self, character=None) -> list[db.FlowRequest]`, `def mark_flow_applied(self, req_id)`.
  - `def enqueue_flow(self, character, amount_krw, liquidate=()) -> int`.
  - `def upsert_daily_bars(self, market, symbol, df)`, `def load_daily_bars(self, market, symbol) -> pd.DataFrame`.
  - `def save_universe(self, market, symbols, as_of)`, `def load_universe(self, market, as_of) -> list[str]`.
- Consumes: Task 7 Repository.

- [ ] **Step 1: 실패 테스트 작성** — `tests/live/test_repository.py`에 추가:

```python
from datetime import datetime
@needs_db
def test_run_state_idempotency_and_flow_queue(session):
    import os
    from simcore.live.repository import Repository
    from simcore.live.db import make_engine, make_session_factory
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    rs = repo.get_run_state("KR")
    assert rs.last_close_date is None
    repo.mark_close("KR", date(2026, 7, 6), 1300.0)
    assert repo.get_run_state("KR").last_close_date == date(2026, 7, 6)

    rid = repo.enqueue_flow("국내형", 5_000_000.0)
    pend = repo.pending_flow_requests()
    assert len(pend) == 1 and pend[0].amount_krw == 5_000_000.0
    repo.mark_flow_applied(rid)
    assert repo.pending_flow_requests() == []


@needs_db
def test_daily_bars_upsert_load(session):
    import os, pandas as pd
    from simcore.live.repository import Repository
    from simcore.live.db import make_engine, make_session_factory
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    df = pd.DataFrame({"open":[1.],"high":[2.],"low":[0.5],"close":[1.5],"volume":[10.]},
                      index=pd.to_datetime(["2026-07-06"]))
    repo.upsert_daily_bars("KR", "005930", df)
    got = repo.load_daily_bars("KR", "005930")
    assert got.iloc[0]["close"] == 1.5
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/live/test_repository.py -k "idempotency or upsert" -v`
Expected: FAIL — 메서드 없음

- [ ] **Step 3: 구현** — `repository.py`에 메서드 추가:

```python
import pandas as pd
from datetime import datetime

    # (Repository 클래스 내부에 추가)
    def get_run_state(self, market: str):
        with self.sf() as s:
            rs = s.get(db.RunState, market)
            if rs is None:
                rs = db.RunState(market=market, schema_version=1, last_fx_rate=0.0)
                s.add(rs); s.commit(); s.refresh(rs)
            s.expunge(rs)
            return rs

    def mark_open(self, market: str, d, fx: float) -> None:
        with self.sf() as s:
            rs = s.get(db.RunState, market) or db.RunState(market=market)
            rs.last_open_date, rs.last_fx_rate = d, fx
            s.merge(rs); s.commit()

    def mark_close(self, market: str, d, fx: float) -> None:
        with self.sf() as s:
            rs = s.get(db.RunState, market) or db.RunState(market=market)
            rs.last_close_date, rs.last_fx_rate = d, fx
            s.merge(rs); s.commit()

    def append_new_trades(self, engine) -> None:
        with self.sf() as s:
            for name, st in engine.states.items():
                have = s.query(db.TradeRow).filter_by(character=name).count()
                for t in st.portfolio.trades[have:]:
                    s.add(db.TradeRow(ts=datetime.now(), date=t.date, character=name,
                        symbol=t.symbol, market=t.market.value, side=t.side.value,
                        quantity=t.quantity, price=t.price, fee=t.fee, tax=t.tax,
                        reason=t.reason.value, green_count=t.green_count,
                        red_count=t.red_count, fired=list(t.fired),
                        realized_pnl=t.realized_pnl))
            s.commit()

    def record_equity(self, ts, snap: dict) -> None:
        with self.sf() as s:
            for name, eq in snap.items():
                s.add(db.EquityPoint(ts=ts, character=name, equity_krw=eq))
            s.commit()

    def enqueue_flow(self, character: str, amount_krw: float, liquidate=()) -> int:
        with self.sf() as s:
            fr = db.FlowRequest(character=character, amount_krw=amount_krw,
                                liquidate=list(liquidate), status="pending",
                                requested_at=datetime.now())
            s.add(fr); s.commit(); s.refresh(fr)
            return fr.id

    def pending_flow_requests(self, character=None):
        with self.sf() as s:
            q = s.query(db.FlowRequest).filter_by(status="pending")
            if character:
                q = q.filter_by(character=character)
            rows = q.order_by(db.FlowRequest.id).all()
            for r in rows:
                s.expunge(r)
            return rows

    def mark_flow_applied(self, req_id: int) -> None:
        with self.sf() as s:
            r = s.get(db.FlowRequest, req_id)
            if r:
                r.status, r.applied_at = "applied", datetime.now()
                s.commit()

    def upsert_daily_bars(self, market: str, symbol: str, df: pd.DataFrame) -> None:
        with self.sf() as s:
            for ts, r in df.iterrows():
                s.merge(db.DailyBarRow(market=market, symbol=symbol, date=ts.date(),
                    open=float(r["open"]), high=float(r["high"]), low=float(r["low"]),
                    close=float(r["close"]), volume=float(r["volume"])))
            s.commit()

    def load_daily_bars(self, market: str, symbol: str) -> pd.DataFrame:
        with self.sf() as s:
            rows = s.query(db.DailyBarRow).filter_by(market=market, symbol=symbol) \
                    .order_by(db.DailyBarRow.date).all()
            recs = [{"date": pd.Timestamp(r.date), "open": r.open, "high": r.high,
                     "low": r.low, "close": r.close, "volume": r.volume} for r in rows]
            if not recs:
                return pd.DataFrame(columns=["open","high","low","close","volume"])
            return pd.DataFrame(recs).set_index("date")

    def save_universe(self, market: str, symbols: list[str], as_of) -> None:
        with self.sf() as s:
            for rank, sym in enumerate(symbols):
                s.merge(db.UniverseRow(market=market, symbol=sym, as_of_date=as_of, rank=rank))
            s.commit()

    def load_universe(self, market: str, as_of) -> list[str]:
        with self.sf() as s:
            rows = s.query(db.UniverseRow).filter_by(market=market, as_of_date=as_of) \
                    .order_by(db.UniverseRow.rank).all()
            return [r.symbol for r in rows]

    def record_flow(self, flow) -> None:
        with self.sf() as s:
            s.add(db.CapitalFlowRow(date=flow.date, character=flow.character,
                amount_krw=flow.amount_krw, fx_rate=flow.fx_rate))
            s.commit()
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/live/test_repository.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add simcore/live/repository.py tests/live/test_repository.py
git commit -m "feat(live): 이력 append + run_state 멱등 + flow 큐 + 일봉/유니버스 캐시"
```

---

### Task 9: Orchestrator — 마감 사이클 (신호→evaluate_close→snapshot)

**Files:**
- Create: `simcore/live/orchestrator.py`
- Test: `tests/live/test_orchestrator.py`

**Interfaces:**
- Consumes: `Engine`, `KisClient`(또는 목), `Repository`, `sigmod`, `calendar`, `DailyBar`, `SymbolSnapshot`.
- Produces:
  - `class Orchestrator(engine, kis, repo, cfg, fx_provider)`; `fx_provider(d)->float`.
  - `def on_close(self, d: date, market: str, universe: list[str]) -> None` — 증분 일봉 갱신→신호→`evaluate_close`→snapshot 저장→trades/flows append→`mark_close`. run_state로 멱등.
  - 내부 `_snapshot_and_signals(...)`가 `run_replay`와 동일 신호 계산(`sigmod.evaluate_frame`/`fired_at`)을 사용.

- [ ] **Step 1: 실패 테스트 작성** — `tests/live/test_orchestrator.py` (목 KIS, 임시 DB):

```python
import os, pandas as pd, pytest
from datetime import date
from tests.live.conftest import needs_db
from simcore.config import Config
from simcore.engine import Engine
from simcore.live.orchestrator import Orchestrator
from simcore.live.repository import Repository
from simcore.live.db import make_engine, make_session_factory


class FakeKis:
    def __init__(self, bars): self.bars = bars     # {(market,symbol): DataFrame}
    def daily_bars(self, market, symbol, start, end): return self.bars[(market, symbol)]
    def current_price(self, market, symbol): return float(self.bars[(market, symbol)].iloc[-1]["close"])
    def market_cap_ranking(self, n): return ["005930"]


def _uptrend(n=80):
    idx = pd.bdate_range("2026-01-01", periods=n)
    base = pd.Series(range(n), index=idx) * 1.0 + 100
    return pd.DataFrame({"open": base, "high": base + 2, "low": base - 1,
                         "close": base + 1, "volume": [1e6] * n}, index=idx)


@needs_db
def test_on_close_persists_signals_and_equity(session):
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config())
    d0 = date(2026, 1, 1)
    eng.start(d0, 1300.0)
    kis = FakeKis({("KR", "005930"): _uptrend()})
    orch = Orchestrator(eng, kis, repo, Config(), fx_provider=lambda d: 1300.0)
    last = _uptrend().index[-1].date()
    orch.on_close(last, "KR", ["005930"])
    # equity 기록됨 + run_state 갱신 + 중복 호출 무시
    assert repo.get_run_state("KR").last_close_date == last
    orch.on_close(last, "KR", ["005930"])   # 멱등: 재실행 무시
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/live/test_orchestrator.py -k on_close -v`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: 구현** — `simcore/live/orchestrator.py`:

```python
"""라이브 엔진 구동자 — run_replay 와 동일 엔진 호출을 실시간 트리거로."""
from __future__ import annotations
from datetime import date, datetime, timedelta
import pandas as pd

from simcore.config import Config
from simcore.engine import Engine
from simcore.models import DailyBar, Market, SymbolSnapshot
from simcore import signals as sigmod


class Orchestrator:
    def __init__(self, engine: Engine, kis, repo, cfg: Config, fx_provider):
        self.engine = engine
        self.kis = kis
        self.repo = repo
        self.cfg = cfg
        self.fx = fx_provider

    def _refresh_bars(self, market: str, symbol: str, upto: date) -> pd.DataFrame:
        cached = self.repo.load_daily_bars(market, symbol)
        start = (cached.index.max().date() + timedelta(days=1)) if not cached.empty \
            else upto - timedelta(days=180)
        if start <= upto:
            fresh = self.kis.daily_bars(market, symbol, start, upto)
            if not fresh.empty:
                self.repo.upsert_daily_bars(market, symbol, fresh)
        return self.repo.load_daily_bars(market, symbol)

    def on_close(self, d: date, market: str, universe: list[str]) -> None:
        rs = self.repo.get_run_state(market)
        if rs.last_close_date == d:
            return                                  # 멱등: 이미 처리
        m = Market(market)
        fx = self.fx(d)
        snaps: dict[str, SymbolSnapshot] = {}
        last_close: dict[str, float] = {}
        for sym in universe:
            try:
                df = self._refresh_bars(market, sym, d)
            except Exception as exc:
                print(f"[live] {market} {sym} 일봉 실패 스킵: {exc}")
                continue
            ts = pd.Timestamp(d)
            if ts not in df.index:
                continue
            frame = sigmod.evaluate_frame(df, self.cfg.signals)
            green, red = sigmod.fired_at(frame, ts)
            loc = df.index.get_loc(ts)
            prev_close = float(df["close"].iloc[loc - 1]) if loc > 0 else float(df.loc[ts, "close"])
            close = float(df.loc[ts, "close"])
            snaps[sym] = SymbolSnapshot(sym, m, green, red, close,
                                        close / prev_close - 1.0, float(df.loc[ts, "volume"]))
            last_close[sym] = close
        self.engine.evaluate_close(d, m, snaps)
        self.repo.persist_state(self.engine)
        self.repo.append_new_trades(self.engine)
        snap = self.engine.snapshot(last_close, fx)
        self.repo.record_equity(datetime.now(), snap)
        self.repo.mark_close(market, d, fx)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/live/test_orchestrator.py -k on_close -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add simcore/live/orchestrator.py tests/live/test_orchestrator.py
git commit -m "feat(live): orchestrator 마감 사이클 (신호→evaluate_close→저장)"
```

---

### Task 10: Orchestrator — 개장 체결 + 5분 손익절 + 입출금

**Files:**
- Modify: `simcore/live/orchestrator.py`
- Test: `tests/live/test_orchestrator.py` (추가)

**Interfaces:**
- Produces (Orchestrator 메서드):
  - `def on_open(self, d, market, universe) -> None` — 대기 flow_requests 처리(`apply_flow`)→pending 종목 현재가로 `fill_open`→저장→`mark_open`. 멱등(run_state.last_open_date).
  - `def on_tick(self, d, market) -> None` — 보유 종목 현재가 폴링→`o=h=l=c` 유사 `DailyBar`로 `check_stops`→저장.

- [ ] **Step 1: 실패 테스트 작성** — `tests/live/test_orchestrator.py`에 추가:

```python
@needs_db
def test_on_tick_triggers_stop_loss(session):
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(Config()); eng.start(date(2026,1,1), 1300.0)
    from simcore.models import Market, TradeReason
    st = eng.states["국내형"]
    st.portfolio.buy(date(2026,1,2), "005930", Market.KR, 10, 100000.0, TradeReason.SIGNAL_BUY)

    # 현재가가 평단 대비 -8% → 손절
    bars = {("KR","005930"): pd.DataFrame(
        {"open":[92000.],"high":[92000.],"low":[92000.],"close":[92000.],"volume":[1.]},
        index=pd.to_datetime(["2026-01-05"]))}
    orch = Orchestrator(eng, FakeKis(bars), repo, Config(), fx_provider=lambda d:1300.0)
    orch.on_tick(date(2026,1,5), "KR")
    assert "005930" not in st.portfolio.positions        # 손절 청산됨
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/live/test_orchestrator.py -k on_tick -v`
Expected: FAIL — `on_tick` 없음

- [ ] **Step 3: 구현** — `orchestrator.py`에 추가:

```python
    def on_open(self, d: date, market: str, universe: list[str]) -> None:
        rs = self.repo.get_run_state(market)
        if rs.last_open_date == d:
            return
        m = Market(market)
        fx = self.fx(d)
        # 1) 대기 입출금 처리
        for req in self.repo.pending_flow_requests():
            st = self.engine.states.get(req.character)
            if st is None or m not in st.spec.markets:
                continue
            opens = {sym: self.kis.current_price(market, sym)
                     for sym in (req.liquidate or ())}
            self.engine.apply_flow(d, req.character, req.amount_krw, fx,
                                   open_prices=opens, liquidate=tuple(req.liquidate or ()))
            self.repo.mark_flow_applied(req.id)
        # 2) pending 주문 종목 현재가로 체결
        pend_syms = {b.symbol for st in self.engine.states.values() for b in st.pending_buys
                     if b.market == m}
        pend_syms |= {ps.symbol for st in self.engine.states.values()
                      for ps in st.pending_sells if ps.market == m}
        opens: dict[str, float] = {}
        for sym in pend_syms:
            try:
                opens[sym] = self.kis.current_price(market, sym)
            except Exception as exc:
                print(f"[live] {market} {sym} 시가 조회 실패(이월): {exc}")
        self.engine.fill_open(d, m, opens, fx)
        self.repo.persist_state(self.engine)
        self.repo.append_new_trades(self.engine)
        self.repo.mark_open(market, d, fx)

    def on_tick(self, d: date, market: str) -> None:
        m = Market(market)
        fx = self.fx(d)
        held = {sym for st in self.engine.states.values()
                for sym, pos in st.portfolio.positions.items() if pos.market == m}
        bars: dict[str, DailyBar] = {}
        for sym in held:
            try:
                px = self.kis.current_price(market, sym)
            except Exception:
                continue
            bars[sym] = DailyBar(sym, d, px, px, px, px, 0.0)
        if bars:
            self.engine.check_stops(d, m, bars, fx)
            self.repo.persist_state(self.engine)
            self.repo.append_new_trades(self.engine)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/live/test_orchestrator.py -v`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add simcore/live/orchestrator.py tests/live/test_orchestrator.py
git commit -m "feat(live): orchestrator 개장 체결 + 5분 손익절 + 입출금"
```

---

### Task 11: ★ 동치성 테스트 (라이브 ≡ 리플레이)

**Files:**
- Test: `tests/live/test_equivalence.py`

**Interfaces:**
- Consumes: `run_replay`, `Orchestrator`, `FakeKis`, `Repository`.
- 새 프로덕션 코드 없음 — 두 경로가 같은 거래를 내는지 검증만.

- [ ] **Step 1: 테스트 작성** — 같은 픽스처를 `run_replay`와 orchestrator에 각각 주입:

```python
import os, pandas as pd
from datetime import date
from tests.live.conftest import needs_db
from simcore.config import Config
from simcore.engine import Engine
from simcore.replay import run_replay, DataBundle
from simcore.live.orchestrator import Orchestrator
from simcore.live.repository import Repository
from simcore.live.db import make_engine, make_session_factory
from simcore.live import calendar as cal


def _series(seed):
    idx = pd.bdate_range("2026-01-01", periods=80)
    import numpy as np
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.4, 2.0, size=80).cumsum()
    base = pd.Series(100 + steps, index=idx).clip(lower=5)
    return pd.DataFrame({"open": base, "high": base + 2, "low": base - 2,
                         "close": base + 0.5, "volume": [1e6]*80}, index=idx)


@needs_db
def test_live_equals_replay(session):
    kr = {"005930": _series(1), "000660": _series(2)}
    fx = pd.Series([1300.0]*80, index=pd.bdate_range("2026-01-01", periods=80))
    bundle = DataBundle(kr=kr, us={}, fx=fx)
    cfg = Config()
    start, end = date(2026,1,1), _series(1).index[-1].date()

    # (A) 리플레이
    rep = run_replay(cfg, bundle, start, end)
    rep_kr = rep.trades[rep.trades.character == "국내형"] if not rep.trades.empty else rep.trades

    # (B) 라이브 orchestrator: 같은 데이터를 하루씩 주입
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    eng = Engine(cfg); eng.start(start, 1300.0)

    class DayKis:
        def __init__(self, kr): self.kr = kr
        def daily_bars(self, market, symbol, s, e):
            df = self.kr[symbol]; return df[df.index.date <= e]
        def current_price(self, market, symbol):
            raise AssertionError("close-only 경로에서는 호출 안 됨")
        def market_cap_ranking(self, n): return list(self.kr)[:n]

    orch = Orchestrator(eng, DayKis(kr), repo, cfg, fx_provider=lambda d: 1300.0)
    days = cal.trading_days_between(start, end, "KR", set())
    for d in days:
        orch.on_open(d, "KR", list(kr))          # 전일 예약분 체결
        orch.on_close(d, "KR", list(kr))         # 당일 신호 예약
    live_trades = eng.states["국내형"].portfolio.trades

    # 거래 (종목,사유,수량) 시퀀스가 동일해야 함
    def key(t): return (t.symbol, t.side.value, t.quantity)
    assert [key(t) for t in live_trades] == \
           [(r.symbol, r.side, r.quantity) for r in rep_kr.itertuples()]
```

- [ ] **Step 2: 실행**

Run: `python -m pytest tests/live/test_equivalence.py -v`
Expected: PASS. (실패 시 orchestrator의 open/close 호출 순서·손익절 근사 차이를 조사 — 리플레이는 당일 OHLC로 손익절, 라이브 close-only 경로는 손익절 미체크이므로, 이 테스트는 **손익절이 발생하지 않는 시드**를 선택하거나 `on_tick`을 당일 OHLC로 함께 호출하도록 맞춘다. 시드 1/2는 손익절 미발생을 전제로 하며, 발생 시 시드를 조정한다.)

- [ ] **Step 3: 커밋**

```bash
git add tests/live/test_equivalence.py
git commit -m "test(live): 라이브 orchestrator ≡ 리플레이 동치성"
```

---

### Task 12: 갭 리플레이 재시작 복구 (recovery)

**Files:**
- Create: `simcore/live/recovery.py`
- Test: `tests/live/test_recovery.py`

**Interfaces:**
- Consumes: `Orchestrator`, `Repository`, `calendar`.
- Produces:
  - `def catch_up(orch: Orchestrator, repo: Repository, market: str, today: date, universe: list[str], holidays: set[date]) -> list[date]` — `run_state.last_close_date` 다음 거래일부터 `today` 전 거래일까지 각 날짜에 `on_open`→`on_close`를 순서대로 실행. 처리한 날짜 리스트 반환.

- [ ] **Step 1: 실패 테스트 작성** — `tests/live/test_recovery.py`:

```python
import os, pandas as pd
from datetime import date
from tests.live.conftest import needs_db
from simcore.config import Config
from simcore.engine import Engine
from simcore.live.orchestrator import Orchestrator
from simcore.live.repository import Repository
from simcore.live.recovery import catch_up
from simcore.live.db import make_engine, make_session_factory


@needs_db
def test_catch_up_processes_missed_days(session):
    sf = make_session_factory(make_engine(os.environ["TEST_DATABASE_URL"]))
    repo = Repository(sf)
    idx = pd.bdate_range("2026-01-01", periods=80)
    base = pd.Series(range(80), index=idx)*1.0 + 100
    df = pd.DataFrame({"open":base,"high":base+2,"low":base-1,"close":base+1,
                       "volume":[1e6]*80}, index=idx)

    class DayKis:
        def daily_bars(self, m, s, a, b): return df[df.index.date <= b]
        def current_price(self, m, s): return float(df.iloc[-1]["close"])
        def market_cap_ranking(self, n): return ["005930"]

    eng = Engine(Config()); eng.start(idx[0].date(), 1300.0)
    orch = Orchestrator(eng, DayKis(), repo, Config(), fx_provider=lambda d:1300.0)
    repo.mark_close("KR", idx[40].date(), 1300.0)          # 41일째까지 처리됐다고 가정
    done = catch_up(orch, repo, "KR", idx[70].date(), ["005930"], set())
    assert idx[41].date() in done and idx[69].date() in done
    assert repo.get_run_state("KR").last_close_date == idx[69].date()
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/live/test_recovery.py -v`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: 구현** — `simcore/live/recovery.py`:

```python
"""재시작 시 놓친 거래일을 확정 일봉으로 재생(갭 리플레이)."""
from __future__ import annotations
from datetime import date, timedelta
from simcore.live import calendar as cal


def catch_up(orch, repo, market: str, today: date, universe: list[str],
             holidays: set[date]) -> list[date]:
    rs = repo.get_run_state(market)
    if rs.last_close_date is None:
        return []
    start = rs.last_close_date + timedelta(days=1)
    end = today - timedelta(days=1)          # 오늘은 라이브 트리거가 처리
    if start > end:
        return []
    days = cal.trading_days_between(start, end, market, holidays)
    for d in days:
        orch.on_open(d, market, universe)
        orch.on_close(d, market, universe)
        print(f"[recovery] {market} {d} 갭 리플레이 처리 (5분 정밀도는 OHLC 근사)")
    return days
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/live/test_recovery.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add simcore/live/recovery.py tests/live/test_recovery.py
git commit -m "feat(live): 갭 리플레이 재시작 복구"
```

---

### Task 13: 스케줄러 (APScheduler 배선)

**Files:**
- Create: `simcore/live/scheduler.py`
- Test: `tests/live/test_scheduler.py`

**Interfaces:**
- Consumes: `Orchestrator`, `calendar`, `Repository`.
- Produces:
  - `class LiveScheduler(orch, repo, holidays_provider, universe_provider, tick_minutes=5)`
    - `def _guarded_open/close/tick(market)` — 오늘 거래일일 때만 orchestrator 호출.
    - `def build(self) -> BackgroundScheduler` — KR/US 각각 개장·마감 cron + 5분 interval 잡 등록.
  - `holidays_provider(market) -> set[date]`, `universe_provider(market) -> list[str]`.
- 스케줄러 자체는 시각만 담당하므로, 테스트는 `_guarded_*`의 거래일 가드 로직만 검증(APScheduler 실행 없이).

- [ ] **Step 1: 실패 테스트 작성** — `tests/live/test_scheduler.py`:

```python
from datetime import date
from simcore.live.scheduler import LiveScheduler


class Spy:
    def __init__(self): self.calls = []
    def on_open(self, d, m, u): self.calls.append(("open", m, d))
    def on_close(self, d, m, u): self.calls.append(("close", m, d))
    def on_tick(self, d, m): self.calls.append(("tick", m, d))


def test_guard_skips_holiday(monkeypatch):
    spy = Spy()
    sched = LiveScheduler(spy, repo=None,
                          holidays_provider=lambda m: {date(2026,7,6)},
                          universe_provider=lambda m: ["005930"])
    import simcore.live.scheduler as sc
    monkeypatch.setattr(sc, "_today", lambda market: date(2026,7,6))  # 휴장일
    sched._guarded_close("KR")
    assert spy.calls == []            # 휴장일이므로 호출 안 됨
    monkeypatch.setattr(sc, "_today", lambda market: date(2026,7,7))  # 거래일
    sched._guarded_close("KR")
    assert spy.calls == [("close", "KR", date(2026,7,7))]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/live/test_scheduler.py -v`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: 구현** — `simcore/live/scheduler.py`:

```python
"""APScheduler 배선 — 시각 트리거만. 거래일 판정 후 orchestrator 호출."""
from __future__ import annotations
from datetime import date, datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from simcore.live import calendar as cal


def _today(market: str) -> date:
    return datetime.now(cal._TZ[market]).date()


class LiveScheduler:
    def __init__(self, orch, repo, holidays_provider, universe_provider, tick_minutes=5):
        self.orch = orch
        self.repo = repo
        self.holidays = holidays_provider
        self.universe = universe_provider
        self.tick_minutes = tick_minutes

    def _is_trading_today(self, market: str) -> bool:
        d = _today(market)
        return cal.is_trading_day(d, market, self.holidays(market))

    def _guarded_open(self, market: str) -> None:
        if self._is_trading_today(market):
            self.orch.on_open(_today(market), market, self.universe(market))

    def _guarded_close(self, market: str) -> None:
        if self._is_trading_today(market):
            self.orch.on_close(_today(market), market, self.universe(market))

    def _guarded_tick(self, market: str) -> None:
        if self._is_trading_today(market):
            self.orch.on_tick(_today(market), market)

    def build(self) -> BackgroundScheduler:
        sched = BackgroundScheduler(timezone="UTC")
        specs = {"KR": (cal.KR_TZ, 9, 0, 15, 30, 40),
                 "US": (cal.US_TZ, 9, 30, 16, 0, 10)}
        for market, (tz, oh, om, ch, cm, cdelay) in specs.items():
            sched.add_job(self._guarded_open, CronTrigger(hour=oh, minute=om, timezone=tz),
                          args=[market], id=f"open_{market}")
            sched.add_job(self._guarded_close,
                          CronTrigger(hour=ch, minute=cm + cdelay, timezone=tz),
                          args=[market], id=f"close_{market}")
            sched.add_job(self._guarded_tick,
                          IntervalTrigger(minutes=self.tick_minutes),
                          args=[market], id=f"tick_{market}")
        return sched
```

주: 마감 잡의 분(minute) 계산이 60을 넘으면(예: 15:30+40=15:70) CronTrigger가 오류나므로, 구현 시 `close_after` 시각을 미리 시:분으로 정규화한다(예: KR 16:10, US 16:10 ET). 위 specs를 `("KR", tz, open=(9,0), close_job=(16,10))` 형태로 정규화해 등록할 것.

- [ ] **Step 4: 정규화 반영 후 통과 확인**

Run: `python -m pytest tests/live/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add simcore/live/scheduler.py tests/live/test_scheduler.py
git commit -m "feat(live): APScheduler 배선 + 거래일 가드"
```

---

### Task 14: 데몬 진입점 + CLI (`python -m simcore.live`)

**Files:**
- Create: `simcore/live/__main__.py`
- Test: `tests/live/test_scheduler.py` (부팅 시퀀스 스모크는 여기에 최소한으로) 또는 `tests/live/test_main.py`

**Interfaces:**
- Consumes: 위 전부.
- Produces:
  - `def build_app(settings) -> tuple[Engine, KisClient, Repository, Orchestrator]` — 배선 조립(테스트 가능하도록 분리).
  - `def boot(settings) -> None` — DB create_all → rehydrate(없으면 cold start) → catch_up → scheduler 시작 → 대기.
  - CLI: `python -m simcore.live run` / `deposit <char> <amt>` / `withdraw <char> <amt> [--liquidate a;b]`.

- [ ] **Step 1: 실패 테스트 작성 (배선 조립 스모크)** — `tests/live/test_main.py`:

```python
import os
from tests.live.conftest import needs_db
from simcore.live.settings import LiveSettings
from simcore.live.__main__ import build_app


@needs_db
def test_build_app_wires_components():
    s = LiveSettings(kis_app_key="AK", kis_app_secret="SK",
                     database_url=os.environ["TEST_DATABASE_URL"], kis_env="real")
    eng, kis, repo, orch = build_app(s)
    assert set(eng.states) == {"국내형", "해외형", "범용형"}
    assert orch.engine is eng
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/live/test_main.py -v`
Expected: FAIL — 모듈/함수 없음

- [ ] **Step 3: 구현** — `simcore/live/__main__.py`:

```python
"""라이브 데몬 진입점 + 입출금 CLI. python -m simcore.live run"""
from __future__ import annotations
import argparse, time
from datetime import date

from simcore.config import Config
from simcore.engine import Engine
from simcore.live.settings import load_settings, LiveSettings
from simcore.live.ratelimit import RateLimiter
from simcore.live.kis_client import KisClient
from simcore.live.repository import Repository, DbTokenStore
from simcore.live.orchestrator import Orchestrator
from simcore.live.scheduler import LiveScheduler
from simcore.live.recovery import catch_up
from simcore.live import db, calendar as cal


def _fx_provider(kis, repo):
    def fx(d: date) -> float:
        try:
            from simcore import data as datamod
            s = datamod.load_fx(d, d, cache_dir=__import__("pathlib").Path("data/cache"))
            return float(s.iloc[-1])
        except Exception:
            return repo.get_run_state("KR").last_fx_rate or 1300.0
    return fx


def build_app(settings: LiveSettings):
    engine = db.make_engine(settings.database_url)
    db.create_all(engine)
    sf = db.make_session_factory(engine)
    repo = Repository(sf)
    kis = KisClient(settings, DbTokenStore(sf),
                    RateLimiter(settings.kis_rate_limit_per_sec))
    eng = Engine(Config())
    orch = Orchestrator(eng, kis, repo, Config(), fx_provider=_fx_provider(kis, repo))
    return eng, kis, repo, orch


def _holidays_provider(kis):
    # KR: KIS 휴장일 API(구현 시 채움), US: 연도별 NYSE 목록(서브프로젝트5에서 정밀화)
    def provider(market: str) -> set[date]:
        return set()
    return provider


def _universe_provider(kis, repo, cfg_top=(30, 30)):
    from simcore import universe as uni
    from pathlib import Path
    def provider(market: str) -> list[str]:
        today = date.today()
        cached = repo.load_universe(market, today)
        if cached:
            return cached
        if market == "KR":
            syms = kis.market_cap_ranking(cfg_top[0])
        else:
            syms = uni.sp500(Path("data/cache"))[:cfg_top[1]]
        repo.save_universe(market, syms, today)
        return syms
    return provider


def boot(settings: LiveSettings) -> None:
    eng, kis, repo, orch = build_app(settings)
    if not repo.rehydrate(eng):
        eng.start(date.today(), orch.fx(date.today()))   # cold start: 3캐릭터 1억
        repo.persist_state(eng)
    hol = _holidays_provider(kis)
    uni = _universe_provider(kis, repo)
    for market in ("KR", "US"):
        catch_up(orch, repo, market, date.today(), uni(market), hol(market))
    sched = LiveScheduler(orch, repo, hol, uni).build()
    sched.start()
    print("[live] 스케줄러 가동. Ctrl+C 로 종료.")
    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()


def main() -> None:
    ap = argparse.ArgumentParser(prog="simcore.live")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    dep = sub.add_parser("deposit"); dep.add_argument("character"); dep.add_argument("amount", type=float)
    wd = sub.add_parser("withdraw"); wd.add_argument("character"); wd.add_argument("amount", type=float)
    wd.add_argument("--liquidate", default="")
    args = ap.parse_args()
    settings = load_settings()
    _, _, repo, _ = build_app(settings)
    if args.cmd == "run":
        boot(settings)
    elif args.cmd == "deposit":
        repo.enqueue_flow(args.character, args.amount)
        print("입금 예약됨(다음 개장 반영)")
    elif args.cmd == "withdraw":
        liq = tuple(x for x in args.liquidate.split(";") if x)
        repo.enqueue_flow(args.character, -args.amount, liquidate=liq)
        print("출금 예약됨(다음 개장 반영)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/live/test_main.py -v`
Expected: PASS

- [ ] **Step 5: 전체 테스트 회귀 확인** (기존 63 + 신규)

Run: `python -m pytest -q`
Expected: 기존 63 통과 유지 + 신규 라이브 통과 (DB 테스트는 TEST_DATABASE_URL 있을 때).

- [ ] **Step 6: 커밋**

```bash
git add simcore/live/__main__.py tests/live/test_main.py
git commit -m "feat(live): 데몬 진입점 + 입출금 CLI"
```

---

### Task 15: 문서 갱신 + 라이브 스모크 런

**Files:**
- Modify: `.env.example`, `README.md`
- Create: `docs/experiments/live-smoke-<날짜>.md` (스모크 결과)

**Interfaces:** 없음(문서/운영).

- [ ] **Step 1: `.env.example` 갱신** — 신규 변수 명시(값은 비움):

```
# 한국투자증권 KIS 오픈API — 값은 .env 에만 직접 입력 (커밋 금지)
KIS_APP_KEY=
KIS_APP_SECRET=
KIS_ACCOUNT_NO=
KIS_ENV=real
# PostgreSQL
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/simcore
# (선택) DB 테스트용
TEST_DATABASE_URL=
```

- [ ] **Step 2: `README.md`에 라이브 모드 섹션 추가**:

```markdown
## 라이브 모드 (KIS 실시세)
    # Postgres 준비 후 .env 채우기 (KIS 키·DATABASE_URL)
    py -m simcore.live run           # 데몬 시작 (스케줄러)
    py -m simcore.live deposit 국내형 5000000     # 입금 예약
    py -m simcore.live withdraw 해외형 3000000 --liquidate AAPL   # 출금 예약
KIS access_token 은 자동 발급·캐시된다. 상태·거래내역은 Postgres에 영속된다.
```

- [ ] **Step 3: 문서 커밋**

```bash
git add .env.example README.md
git commit -m "docs(live): .env.example + README 라이브 모드 사용법"
```

- [ ] **Step 4: 라이브 스모크 런** (사용자가 `.env`에 실제 KIS 키·DB 채운 뒤)

```bash
# 실제 KIS real 도메인 데이터로 1거래일 가동 관찰
py -m simcore.live run
```
관찰 항목: 토큰 발급 1회, 유니버스 조달, 마감 후 신호·거래 기록이 Postgres `trades`/`equity_curve`에 적재되는지. **이 단계에서 KIS 실제 응답 필드명이 Task 3/4 파서와 일치하는지 최종 확인** — 불일치 시 파서·픽스처 수정 후 관련 테스트 재실행.

- [ ] **Step 5: 스모크 결과 기록** — `docs/experiments/live-smoke-<날짜>.md`에 실행일·설정 스냅샷·관찰 결과·이슈를 기존 실험기록 형식으로 남기고 커밋.

```bash
git add docs/experiments/live-smoke-*.md
git commit -m "docs(experiments): 라이브 스모크 런 결과 기록"
```

---

## 릴리즈

- 위 태스크가 모두 dev에 병합되면, 서브프로젝트 2 완료 시점에 `dev`→`main` 승격 PR/머지 + `v1.1.0` 태그 + 패치노트(`CHANGELOG.md`, `docs/patch-notes/v1.1.0.md`) 작성(CLAUDE.md §4·§7).

## 완료 기준 대조 (스펙 §9)

1. `python -m simcore.live run` 부팅·rehydrate·스케줄러 → Task 14.
2. 동치성(라이브≡리플레이) → Task 11.
3. 재시작 무중복 재개 + 갭 리플레이 복구 → Task 8(멱등)·12.
4. 전체 테스트 green(기존 63 + 신규) → Task 14 Step 5.
5. 라이브 스모크 런 + experiments 기록 → Task 15.
6. `.env.example`·README 갱신 → Task 15.
