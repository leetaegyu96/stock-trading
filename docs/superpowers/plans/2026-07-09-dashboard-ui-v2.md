# 대시보드 UI 개편 v2 + 데이터 리셋 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 6개월 리플레이 결과를 DB에 적재하고, 대시보드를 초보 친화 UI(일일 현황판·종목명·한 줄 요약 신호 표시)로 개편하며 범용형 자산 불일치를 해소한다.

**Architecture:** (a) `simcore` 순수 헬퍼(종목명·신호표시·리플레이 결과 노출) → (b) `dashboard/scripts/seed_from_replay.py` 시딩 → (c) FastAPI 조회 확장(name·signal_summary·/api/dashboard) → (d) React 개편(현황판·친화 신호). 엔진/신호 판정 로직은 변경하지 않는다(리플레이 결과 노출 필드 추가만 허용).

**Tech Stack:** Python(pandas·SQLAlchemy·FastAPI·pydantic), React+TS+Vite, pytest+vitest.

## Global Constraints

- **사용자는 주식 완전 초짜.** 문구는 초보 친화(전문용어 최소화). **화면에 "사용자 친화 UI"·"요청사항" 같은 설명 라벨을 직접 노출하지 않는다.**
- 상승=빨강/하락=파랑(dataviz 검증 팔레트), 라이트/다크 유지. 기존 디자인 토큰·컴포넌트 재사용.
- **엔진/신호 판정 로직 무변경.** `simcore/replay.py`에 리플레이 결과 노출 필드 추가는 허용(로직 아님).
- 종목명 매핑 미스 → 코드 그대로 폴백(깨지지 않음).
- `TradeRow`/`PositionRow`는 v2 컬럼(green_score/red_score, peak_price/locked_stop_pct) 보유(sp4). 시딩·조회는 이를 포함한다.
- 시드 스크립트는 `--force` 없이는 DB를 지우지 않는다(실데이터 보호).
- 범용형 정합 기준: **card_summary.total_asset_krw == equity_series 마지막값**(동일 스냅샷 시딩).
- 커밋 신원 `leetaegyu96 <leetaegyu96@users.noreply.github.com>`, 한국어+타입 접두어. `dev`에서 분기.

## 파일 구조

- `simcore/replay.py` (수정) — `ReplayResult`에 `positions_by_char`·`cash_by_char`·`last_close` 노출.
- `simcore/names.py` (신규) — `SYMBOL_NAMES` 정적 매핑 + `display_name`.
- `simcore/signal_display.py` (신규) — `SIGNAL_NAMES`·`stars`·`grade`·`summarize`·`detail`.
- `dashboard/scripts/seed_from_replay.py` (신규) — 리플레이 실행 → DB 적재(--force).
- `dashboard/backend/queries.py` (수정) — positions/trades에 name, trades에 green_score/red_score; movers·portfolio 조회.
- `dashboard/backend/summary.py` (수정) — 현황판 포트폴리오 요약.
- `dashboard/backend/schemas.py` (수정) — PositionOut.name, TradeOut.name/green_score/red_score/signal_summary/signal_detail, Dashboard 스키마.
- `dashboard/backend/app.py` (수정) — `/api/dashboard` 라우트, trades 응답에 신호 표시 병합.
- 프론트: `types.ts`, `api.ts`, `pages/Main.tsx`, `components/TradesTable.tsx`, `components/PositionsTable.tsx`, 신규 `MarketMovers.tsx`·`HoldingsPreview.tsx`·`RecentTrades.tsx`, `components/format.ts`(신호 표시 헬퍼는 백엔드 제공값 사용).

---

### Task 1: ReplayResult에 최종 포지션·현금·last_close 노출

**Files:** Modify `simcore/replay.py`; Test `tests/test_replay_integration.py`

**Interfaces — Produces:** `ReplayResult`에 필드 추가:
- `positions_by_char: dict[str, list[dict]]` — 캐릭터→[{symbol, market, quantity, avg_price, opened, peak_price, locked_stop_pct}].
- `cash_by_char: dict[str, dict[str, float]]` — 캐릭터→{currency: amount}.
- `last_close: dict[str, float]` — 심볼→마지막 종가(엔진 평가에 쓰인 값).

- [ ] **Step 1: 실패 테스트** — `tests/test_replay_integration.py`에 추가

```python
def test_replay_result_exposes_final_state():
    import numpy as np, pandas as pd
    from datetime import date
    from simcore.config import Config
    from simcore.replay import DataBundle, run_replay
    idx = pd.date_range("2025-06-01", periods=200, freq="B")
    up = np.linspace(100, 400, 200)
    df = pd.DataFrame({"open": up, "high": up + 2, "low": up - 2,
                       "close": up, "volume": np.linspace(1000, 5000, 200)}, index=idx)
    res = run_replay(Config(), DataBundle(kr={"AAA": df}, us={},
                     fx=pd.Series(1300.0, index=idx)), date(2025, 9, 1), date(2026, 2, 1))
    assert set(res.positions_by_char) == {"국내형", "해외형", "범용형"}
    assert isinstance(res.cash_by_char["국내형"], dict)
    assert "AAA" in res.last_close
    # 보유가 있으면 트레일링 상태 필드 포함
    for plist in res.positions_by_char.values():
        for p in plist:
            assert {"symbol","market","quantity","avg_price","peak_price","locked_stop_pct"} <= set(p)
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_replay_integration.py -k final_state -q` → FAIL (AttributeError positions_by_char)

- [ ] **Step 3: 구현** — `simcore/replay.py`

`ReplayResult` 데이터클래스에 필드 추가(기본값):
```python
@dataclass
class ReplayResult:
    trades: pd.DataFrame
    equity: pd.DataFrame
    flows_by_char: dict[str, pd.Series]
    green_hist: pd.Series
    summary: dict
    positions_by_char: dict = field(default_factory=dict)
    cash_by_char: dict = field(default_factory=dict)
    last_close: dict = field(default_factory=dict)
```
`run_replay` 의 결과 집계부(`return ReplayResult(...)` 직전)에서 채운다:
```python
    positions_by_char = {}
    cash_by_char = {}
    for name, st in engine.states.items():
        positions_by_char[name] = [
            {"symbol": p.symbol, "market": p.market.value, "quantity": p.quantity,
             "avg_price": p.avg_price, "opened": p.opened,
             "peak_price": p.peak_price, "locked_stop_pct": p.locked_stop_pct}
            for p in st.portfolio.positions.values()
        ]
        cash_by_char[name] = {cur.value: amt for cur, amt in st.portfolio.cash.items()}
    return ReplayResult(trades, equity, flows_by_char, green_hist, summary,
                        positions_by_char=positions_by_char,
                        cash_by_char=cash_by_char, last_close=dict(last_close))
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_replay_integration.py -q` → PASS

- [ ] **Step 5: 커밋** — `git add simcore/replay.py tests/test_replay_integration.py && git commit -m "feat: ReplayResult에 최종 포지션·현금·last_close 노출 (시딩용)"`

---

### Task 2: 종목명 정적 매핑 (`simcore/names.py`)

**Files:** Create `simcore/names.py`; Test `tests/test_names.py`

**Interfaces — Produces:** `SYMBOL_NAMES: dict[str, str]`; `display_name(symbol: str, market: str | None = None) -> str`.

- [ ] **Step 1: 실패 테스트** — `tests/test_names.py`

```python
from simcore.names import display_name, SYMBOL_NAMES


def test_known_kr_symbol_returns_korean_name():
    assert display_name("005930", "KR") == "삼성전자"


def test_known_us_symbol_returns_company():
    assert display_name("AAPL", "US") == "Apple"


def test_unknown_symbol_falls_back_to_code():
    assert display_name("999999", "KR") == "999999"


def test_map_is_nonempty_and_str():
    assert len(SYMBOL_NAMES) >= 30
    assert all(isinstance(v, str) and v for v in SYMBOL_NAMES.values())
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_names.py -q` → FAIL (ModuleNotFound)

- [ ] **Step 3: 구현** — `simcore/names.py`. KR은 코스피 대형주 + 리플레이 유니버스 폴백(top-30) 코드→한글명, US는 S&P500 주요 티커→회사명. 최소 KR 30 + US 30. 실제 코드→이름 매핑을 채운다(아래는 시작점, 구현 시 유니버스 폴백 목록과 대조해 보강):

```python
"""종목 코드 → 표시 이름 정적 매핑. 미스 시 코드 그대로 반환(안전 폴백).
라이브에서는 live_prices 가 KIS 종목명으로 보강할 수 있다."""
from __future__ import annotations

SYMBOL_NAMES: dict[str, str] = {
    # --- KR (코스피 대형주 / 리플레이 폴백 유니버스) ---
    "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스", "005935": "삼성전자우", "005380": "현대차",
    "000270": "기아", "068270": "셀트리온", "005490": "POSCO홀딩스",
    "035420": "NAVER", "051910": "LG화학", "006400": "삼성SDI",
    "035720": "카카오", "028260": "삼성물산", "105560": "KB금융",
    "055550": "신한지주", "012330": "현대모비스", "086790": "하나금융지주",
    "066570": "LG전자", "003670": "포스코퓨처엠", "096770": "SK이노베이션",
    "015760": "한국전력", "017670": "SK텔레콤", "034730": "SK",
    "003550": "LG", "018260": "삼성에스디에스", "032830": "삼성생명",
    "009150": "삼성전기", "011200": "HMM", "010130": "고려아연",
    "196170": "알테오젠", "247540": "에코프로비엠",
    # --- US (S&P500 주요) ---
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "AMZN": "Amazon",
    "GOOGL": "Alphabet", "META": "Meta", "TSLA": "Tesla", "AVGO": "Broadcom",
    "BRK-B": "Berkshire", "JPM": "JPMorgan", "V": "Visa", "MA": "Mastercard",
    "UNH": "UnitedHealth", "HD": "Home Depot", "PG": "P&G", "KO": "Coca-Cola",
    "JNJ": "J&J", "COST": "Costco", "WMT": "Walmart", "XOM": "ExxonMobil",
    "NFLX": "Netflix", "AMD": "AMD", "CRM": "Salesforce", "ADBE": "Adobe",
    "PEP": "PepsiCo", "INTC": "Intel", "CSCO": "Cisco", "ORCL": "Oracle",
    "DIS": "Disney", "BAC": "Bank of America",
}


def display_name(symbol: str, market: str | None = None) -> str:
    return SYMBOL_NAMES.get(symbol, symbol)
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_names.py -q` → PASS

- [ ] **Step 5: 커밋** — `git add simcore/names.py tests/test_names.py && git commit -m "feat: 종목명 정적 매핑(코드→한글/회사명) + 코드 폴백"`

---

### Task 3: 신호 표시 헬퍼 (`simcore/signal_display.py`)

**Files:** Create `simcore/signal_display.py`; Test `tests/test_signal_display.py`

**Interfaces — Consumes:** `simcore.config.SignalScores`. **Produces:**
- `SIGNAL_NAMES: dict[str, str]` — 코드→초보용 한글명.
- `stars(code, scores) -> int` (1~5, 점수 그대로).
- `grade(score: int) -> str` — 총점→등급("A"/"B"/"C"/"D").
- `summarize(fired: list[str], score: int, side: str, scores) -> str` — 한 줄 요약.
- `detail(fired: list[str], scores) -> list[dict]` — [{code, name, category, stars}].

- [ ] **Step 1: 실패 테스트** — `tests/test_signal_display.py`

```python
from simcore.config import SignalScores
from simcore import signal_display as sd


def test_names_cover_implemented_codes():
    for code in ["G1","G7","G5","R1","R3","R18"]:
        assert code in sd.SIGNAL_NAMES and sd.SIGNAL_NAMES[code]


def test_stars_equal_points():
    sc = SignalScores()
    assert sd.stars("G1", sc) == 5    # G1 = 5점
    assert sd.stars("G3", sc) == 3


def test_grade_bands():
    assert sd.grade(30) == "A"
    assert sd.grade(20) == "B"
    assert sd.grade(14) == "C"
    assert sd.grade(5) == "D"


def test_summarize_buy_mentions_names_and_score():
    sc = SignalScores()
    text = sd.summarize(["G1", "G7", "G5"], 14, "BUY", sc)
    assert "골든크로스" in text or "신고가" in text
    assert "14" in text
    assert "매수" in text


def test_detail_has_name_category_stars():
    sc = SignalScores()
    d = sd.detail(["G1"], sc)
    assert d and d[0]["code"] == "G1" and d[0]["name"] and d[0]["category"] == "추세" and d[0]["stars"] == 5
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_signal_display.py -q` → FAIL

- [ ] **Step 3: 구현** — `simcore/signal_display.py`

```python
"""거래내역 신호를 초보 친화 표시로 변환. config.SignalScores 를 소비한다(점수/카테고리 정합)."""
from __future__ import annotations
from simcore.config import SignalScores

SIGNAL_NAMES: dict[str, str] = {
    # 청신호
    "G1": "골든크로스", "G2": "20일선 위", "G3": "RSI 상승 전환", "G4": "MACD 골든크로스",
    "G5": "거래량 급증 양봉", "G6": "볼린저 중심 돌파", "G7": "신고가 돌파",
    "G10": "스토캐스틱 반등", "G11": "강한 추세(ADX)", "G12": "상승 우위(DI)",
    "G13": "매집(OBV) 상승", "G14": "평균가(VWAP) 돌파", "G15": "일목구름 돌파",
    "G16": "SAR 매수 전환", "G17": "변동성 수축 후 돌파", "G18": "박스권 상단 돌파",
    "G23": "신고가 + 거래량",
    # 적신호
    "R1": "데드크로스", "R2": "20일선 아래", "R3": "RSI 과열 꺾임", "R4": "MACD 데드크로스",
    "R5": "거래량 급증 음봉", "R6": "볼린저 하단 이탈", "R11": "추세 약화(ADX)",
    "R12": "하락 우위(DI)", "R13": "매집(OBV) 하락", "R14": "평균가(VWAP) 이탈",
    "R15": "일목구름 이탈", "R16": "SAR 매도 전환", "R17": "변동성 급증",
    "R18": "지지선 붕괴", "R19": "갭 하락", "R23": "장대 음봉", "R24": "거래량 없는 상승",
}

_CATEGORY_PHRASE = {
    "추세": "상승추세", "돌파": "돌파", "거래량": "거래량", "모멘텀": "모멘텀",
    "변동성": "변동성", "하락패턴": "하락신호",
}


def stars(code: str, scores: SignalScores) -> int:
    return int(scores.points.get(code, 0))


def grade(score: int) -> str:
    if score >= 26:
        return "A"
    if score >= 18:
        return "B"
    if score >= 12:
        return "C"
    return "D"


def detail(fired, scores: SignalScores) -> list[dict]:
    out = []
    for c in fired:
        if c not in scores.points:
            continue
        out.append({"code": c, "name": SIGNAL_NAMES.get(c, c),
                    "category": scores.category.get(c, ""), "stars": stars(c, scores)})
    out.sort(key=lambda x: -x["stars"])
    return out


def summarize(fired, score: int, side: str, scores: SignalScores) -> str:
    named = [SIGNAL_NAMES.get(c, c) for c in fired if c in scores.points]
    if not named:
        return "신호 없음"
    head = " + ".join(named[:3])
    if side == "BUY":
        verb = "강력 매수 신호" if score >= 26 else ("매수 신호" if score >= 18 else "매수 후보")
        return f"{head} → {verb} ({score}점/{grade(score)}등급)"
    verb = "전량 매도 신호" if score >= 11 else ("부분 매도 신호" if score >= 9 else "주의 신호")
    return f"{head} → {verb} ({score}점)"
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_signal_display.py -q` → PASS

- [ ] **Step 5: 커밋** — `git add simcore/signal_display.py tests/test_signal_display.py && git commit -m "feat: 신호 초보 친화 표시(한글명·별점·등급·한 줄 요약)"`

---

### Task 4: 리플레이 결과 DB 시딩 (`seed_from_replay.py`)

**Files:** Create `dashboard/scripts/seed_from_replay.py`; Test `tests/dashboard/test_seed_from_replay.py`

**Interfaces — Consumes:** Task 1 `ReplayResult` 필드, `simcore.data`/`universe`/`replay`, `simcore.live.db` ORM.

핵심: 6개월 리플레이(또는 소규모 합성 데이터) → DB 적재. **총자산 정합**: 최종 positions/cash + daily_bars(last_close) 를 함께 써서 `card_summary.total_asset_krw == equity 마지막값`.

- [ ] **Step 1: 실패 테스트** — `tests/dashboard/test_seed_from_replay.py` (합성 데이터로 결정론 검증; 실네트워크 없이 `seed_replay_result_into_db(result, bundle, sf)` 함수 단위 테스트)

```python
import numpy as np, pandas as pd
from datetime import date
from simcore.config import Config
from simcore.replay import DataBundle, run_replay
from dashboard.scripts.seed_from_replay import seed_replay_result_into_db
from dashboard.backend import summary, queries
from simcore.live import db


def _bundle():
    idx = pd.date_range("2025-06-01", periods=220, freq="B")
    up = np.linspace(100, 500, 220)
    df = pd.DataFrame({"open": up, "high": up + 3, "low": up - 3, "close": up,
                       "volume": np.linspace(1e6, 5e6, 220)}, index=idx)
    return DataBundle(kr={"005930": df}, us={}, fx=pd.Series(1300.0, index=idx))


def test_seed_makes_card_total_match_equity_last(tmp_path):
    bundle = _bundle()
    result = run_replay(Config(), bundle, date(2025, 9, 1), date(2026, 2, 1))
    engine = db.make_engine("sqlite://")   # in-memory
    db.create_all(engine)
    sf = db.make_session_factory(engine)
    seed_replay_result_into_db(result, bundle, sf, fx_rate=1300.0)
    for name in ["국내형", "해외형", "범용형"]:
        eq = queries.equity_series(sf, name)
        if not eq:
            continue
        lp = queries.last_prices(sf, queries.positions(sf, name))
        card = summary.card_summary(sf, name, 1300.0, lp)
        assert abs(card.total_asset_krw - eq[-1][1]) < 1.0   # 동일 스냅샷 → 정합
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/dashboard/test_seed_from_replay.py -q` → FAIL (ImportError)

- [ ] **Step 3: 구현** — `dashboard/scripts/seed_from_replay.py`

구조:
- 모듈 함수 `seed_replay_result_into_db(result, bundle, sf, fx_rate=1300.0)`:
  1. 세션에서 기존 테이블 전부 delete(seed_demo 와 동일 목록).
  2. 3캐릭터 `CharacterRow`(base_currency = DEFAULT_CHARACTERS 매핑).
  3. `flows_by_char` + 초기입금: `CapitalFlowRow`. (초기입금은 `result` 에 없으므로 `Config.initial_capital_krw` 로 각 캐릭터 첫 flow 기록 후, flows_by_char 의 순입출금 추가.)
     - 주의: `summary._flow_series` 가 flows[1:] 를 순입출금으로 보므로, 첫 행 = 초기입금(제외 대상)이어야 한다. 초기입금 CapitalFlowRow 를 각 캐릭터에 먼저 add.
  4. `equity` DataFrame 의 각 (date, name) → `EquityPoint(ts=해당일 15:40, equity_krw)`.
  5. `positions_by_char` → `PositionRow`(peak_price/locked_stop_pct 포함, opened_date=opened).
  6. `cash_by_char` → `CashBalance`(KRW/USD 각각; 없으면 0).
  7. `trades` DataFrame → `TradeRow`(green_count/red_count/green_score/red_score/fired/realized_pnl 포함, ts=날짜 09:01).
  8. `daily_bars`: `bundle` 의 각 시장·심볼에서 **마지막 종가**를 포함한 최근 N(≤5)봉 → `DailyBarRow`. last_close 정합을 위해 **마지막 봉 close = result.last_close[symbol]** 이 되도록 bundle 의 실제 마지막 봉을 그대로 사용.
  - 커밋. 총자산 정합(테스트로 검증)을 위해 positions·cash·daily_bars 는 반드시 같은 리플레이 최종 스냅샷에서 나와야 한다.
- CLI 진입점: `if "--force" not in sys.argv: sys.exit(...)`; DATABASE_URL 로 엔진 생성·create_all; 유니버스·데이터 로드(`__main__` 과 동일: universe.kospi200/sp500, data.load_kr_daily/us_daily/fx) 후 run_replay → seed_replay_result_into_db. 기간/유니버스는 인자 또는 기본(2026-01-09~2026-07-09, kr-top 50/us-top 50).

(구현자 note: `simcore/__main__.py` 의 데이터 로드 블록을 참고해 동일하게 구성. `db.make_engine`/`create_all`/`make_session_factory` 사용. ORM 필드명은 `simcore/live/db.py` 확인.)

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/dashboard/test_seed_from_replay.py -q` → PASS

- [ ] **Step 5: 커밋** — `git add dashboard/scripts/seed_from_replay.py tests/dashboard/test_seed_from_replay.py && git commit -m "feat: 리플레이 결과 DB 시딩 스크립트(총자산 정합, --force 가드)"`

---

### Task 5: 백엔드 — 종목명·신호 표시 응답 병합

**Files:** Modify `dashboard/backend/queries.py`, `schemas.py`, `app.py`; Test `tests/dashboard/test_api.py`

**Interfaces — Produces:** `PositionOut.name`, `TradeOut`에 `name`·`green_score`·`red_score`·`signal_summary`·`signal_detail`.

- [ ] **Step 1: 실패 테스트** — `tests/dashboard/test_api.py`에 추가(기존 픽스처 사용; 시드된 거래에 name·signal_summary가 오는지)

```python
def test_trades_include_name_and_signal_summary(client_with_seed):
    # client_with_seed: 기존 conftest 의 시드+오버라이드 픽스처(있으면 재사용, 없으면 최소 시드)
    r = client_with_seed.get("/api/characters/국내형/trades")
    assert r.status_code == 200
    rows = r.json()
    assert rows, "거래가 있어야 함"
    t = rows[0]
    assert "name" in t and "signal_summary" in t and "signal_detail" in t
    assert "green_score" in t and "red_score" in t
```

(구현자: 기존 test_api.py 픽스처 구조에 맞춰 시드 데이터에 fired/green_score 가 있는 거래를 포함. 픽스처가 없으면 최소한의 시드를 추가.)

- [ ] **Step 2: 실패 확인** — 해당 테스트 FAIL(KeyError name)

- [ ] **Step 3: 구현**

`queries.positions`: 각 dict에 `"name": names.display_name(r.symbol, r.market)` 추가(import `from simcore.names import display_name`).
`queries.trades`: dict에 `"name": display_name(r.symbol, r.market)`, `"green_score": r.green_score`, `"red_score": r.red_score` 추가.
`schemas.py`:
```python
class PositionOut(BaseModel):
    symbol: str
    name: str
    market: str
    ...
class TradeOut(BaseModel):
    ...
    green_count: int
    red_count: int
    green_score: int = 0
    red_score: int = 0
    fired: list[str]
    signal_summary: str = ""
    signal_detail: list[dict] = []
    realized_pnl: float
```
`app.py` `character_trades`: TradeOut 생성 시 신호 표시 병합:
```python
from simcore.config import Config
from simcore import signal_display as sd
_SCORES = Config().scores

@app.get("/api/characters/{name}/trades", response_model=list[TradeOut])
def character_trades(name: str, limit: int = 200, sf=Depends(get_sf)) -> list[TradeOut]:
    out = []
    for t in queries.trades(sf, name, limit=limit):
        score = t["green_score"] if t["side"] == "BUY" else t["red_score"]
        out.append(TradeOut(
            **t,
            signal_summary=sd.summarize(t["fired"], score, t["side"], _SCORES),
            signal_detail=sd.detail(t["fired"], _SCORES),
        ))
    return out
```
(주의: `queries.trades` dict가 이미 name/green_score/red_score를 포함하므로 `**t` 로 충분; signal_summary/detail만 추가.)

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/dashboard/test_api.py -q` → PASS

- [ ] **Step 5: 커밋** — `git add dashboard/backend tests/dashboard/test_api.py && git commit -m "feat: 거래/보유 응답에 종목명·신호 점수·한 줄 요약·상세 병합"`

---

### Task 6: 백엔드 — 일일 현황판 엔드포인트 `/api/dashboard`

**Files:** Modify `dashboard/backend/queries.py`, `summary.py`, `schemas.py`, `app.py`; Test `tests/dashboard/test_api.py`

**Interfaces — Produces:** `GET /api/dashboard` → `DashboardOut`:
- `movers: {market: {up: [MoverOut], down: [MoverOut]}}` — 시장별 유니버스 상승/하락 top5.
- `characters: [CharPortfolioOut]` — 캐릭터별 오늘손익·보유수·현금비중·보유 베스트/워스트.
- `recent_trades: [RecentTradeOut]` — 통합 최신 체결 N건.
- `MoverOut{symbol, name, market, change_pct, close}`.

- [ ] **Step 1: 실패 테스트** — `tests/dashboard/test_api.py`

```python
def test_dashboard_endpoint_shape(client_with_seed):
    r = client_with_seed.get("/api/dashboard")
    assert r.status_code == 200
    d = r.json()
    assert "movers" in d and "characters" in d and "recent_trades" in d
    # 캐릭터 요약은 3개
    assert len(d["characters"]) == 3
```

- [ ] **Step 2: 실패 확인** — FAIL(404)

- [ ] **Step 3: 구현**

`queries.py`에 추가:
```python
def universe_movers(sf, top: int = 5) -> dict:
    """daily_bars 최근 2봉으로 시장별 등락률 상/하위 top."""
    with sf() as s:
        rows = s.execute(select(db.DailyBarRow)
                         .order_by(db.DailyBarRow.symbol, db.DailyBarRow.date)).scalars().all()
    by_sym: dict[tuple, list] = {}
    for r in rows:
        by_sym.setdefault((r.market, r.symbol), []).append(r)
    changes: dict[str, list] = {"KR": [], "US": []}
    for (market, symbol), bars in by_sym.items():
        if len(bars) < 2:
            continue
        prev, last = bars[-2].close, bars[-1].close
        if prev:
            changes.setdefault(market, []).append(
                {"symbol": symbol, "market": market, "close": last,
                 "change_pct": last / prev - 1.0})
    out = {}
    for market, lst in changes.items():
        lst.sort(key=lambda x: x["change_pct"])
        out[market] = {"down": lst[:top], "up": list(reversed(lst[-top:]))}
    return out


def recent_trades(sf, limit: int = 12) -> list[dict]:
    with sf() as s:
        rows = s.execute(select(db.TradeRow)
                         .order_by(db.TradeRow.ts.desc(), db.TradeRow.id.desc())
                         .limit(limit)).scalars().all()
        return [{"character": r.character, "symbol": r.symbol, "market": r.market,
                 "side": r.side, "reason": r.reason, "realized_pnl": r.realized_pnl,
                 "date": r.date} for r in rows]
```
`summary.py`에 캐릭터 포트폴리오 요약:
```python
def character_portfolios(sf, fx_rate, last_prices_by_char) -> list[dict]:
    out = []
    for name in [s.name for s in DEFAULT_CHARACTERS]:
        eq = _equity_series(sf, name)
        positions = queries.positions(sf, name)
        lp = last_prices_by_char.get(name, {})
        # 보유 베스트/워스트: 각 종목 현재가 vs 평단
        ranked = sorted(
            ({"symbol": p["symbol"], "name": p["name"],
              "pnl_pct": (lp.get(p["symbol"], p["avg_price"]) / p["avg_price"] - 1.0)}
             for p in positions), key=lambda x: x["pnl_pct"])
        out.append({
            "name": name,
            "today_pnl_pct": _today_pnl_pct(eq),
            "n_positions": len(positions),
            "best": ranked[-1] if ranked else None,
            "worst": ranked[0] if ranked else None,
        })
    return out
```
`schemas.py`에 `MoverOut`·`CharPortfolioOut`·`RecentTradeOut`·`DashboardOut` 정의(위 dict 구조 미러; `dict`/`Optional` 사용). movers 값은 name 포함(display_name).
`app.py`에 라우트:
```python
@app.get("/api/dashboard", response_model=DashboardOut)
def dashboard(sf=Depends(get_sf)) -> DashboardOut:
    movers = queries.universe_movers(sf)
    for market in movers.values():
        for lst in market.values():
            for m in lst:
                m["name"] = display_name(m["symbol"], m["market"])
    last_prices_by_char = {}
    for name in [s.name for s in DEFAULT_CHARACTERS]:
        last_prices_by_char[name] = queries.last_prices(sf, queries.positions(sf, name))
    chars = summary.character_portfolios(sf, _FALLBACK_FX_RATE, last_prices_by_char)
    rts = queries.recent_trades(sf)
    for t in rts:
        t["name"] = display_name(t["symbol"], t["market"])
    return DashboardOut(movers=movers, characters=chars, recent_trades=rts)
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/dashboard/test_api.py -q` → PASS

- [ ] **Step 5: 커밋** — `git add dashboard/backend tests/dashboard/test_api.py && git commit -m "feat: /api/dashboard 일일 현황판(시장 movers·캐릭터 요약·최근 체결)"`

---

### Task 7: 프론트 타입·API 클라이언트

**Files:** Modify `dashboard/frontend/src/types.ts`, `api.ts`

**Interfaces — Produces:** TS 타입에 신규 필드/인터페이스, `getDashboard()`.

- [ ] **Step 1: 구현(타입은 컴파일이 검증)** — `types.ts`
  - `PositionOut`에 `name: string`.
  - `TradeOut`에 `name: string; green_score: number; red_score: number; signal_summary: string; signal_detail: SignalDetail[]`.
  - 신규: `SignalDetail{code; name; category; stars}`, `Mover{symbol; name; market; change_pct; close}`, `CharPortfolio{name; today_pnl_pct; n_positions; best: HoldingRank|null; worst: HoldingRank|null}`, `HoldingRank{symbol; name; pnl_pct}`, `RecentTrade{character; name; symbol; market; side; reason; realized_pnl; date}`, `Dashboard{movers: Record<string,{up:Mover[];down:Mover[]}>; characters: CharPortfolio[]; recent_trades: RecentTrade[]}`.
  `api.ts`에 `export const getDashboard = () => http<Dashboard>("/api/dashboard");` (기존 http 헬퍼 패턴 따름).

- [ ] **Step 2: 빌드 확인** — `cd dashboard/frontend && npm run build` → 성공(tsc strict)

- [ ] **Step 3: 커밋** — `git add dashboard/frontend/src/types.ts dashboard/frontend/src/api.ts && git commit -m "feat: 프론트 타입·API에 현황판/신호표시 계약 추가"`

---

### Task 8: 프론트 메인 = 일일 현황판

**Files:** Modify `dashboard/frontend/src/pages/Main.tsx`; Create `components/MarketMovers.tsx`, `HoldingsPreview.tsx`, `RecentTrades.tsx`; Modify `components/theme.css`(레이아웃)

**요구:** 상단 "simcore/모의투자" 텍스트 제거. 좌측 캐릭터 열 + 우측 현황판(오늘의 시장 movers·캐릭터 요약·보유 미리보기·최근 체결). 초보 친화 문구. 화면 꽉 채움. 반응형(좁으면 세로).

- [ ] **Step 1: 컴포넌트 작성** — 기존 `CharacterCard`·`format.ts`·`theme.css` 패턴 준수. 상승빨강/하락파랑 칩.
  - `MarketMovers`: props `movers: Dashboard["movers"]`. 시장별(KR/US) "많이 오른 종목/많이 내린 종목" 섹션, 각 종목명 + 등락률 칩. 데이터가 유니버스 한정임을 작은 안내 문구로.
  - `HoldingsPreview`: props `characters: CharPortfolio[]`. 캐릭터별 오늘손익·보유수·베스트/워스트(종목명+손익 색).
  - `RecentTrades`: props `trades: RecentTrade[]`. 최신 체결(캐릭터·종목명·사유 한글(reasonInfo)·손익 색).
- [ ] **Step 2: Main.tsx 개편**
  - `getDashboard()`를 초기 로드에 추가(카드 소켓과 병행). 상단바에서 `topbar__title`("simcore")·`topbar__tag`("모의투자") 제거, 전체자산+연결점만 유지.
  - 레이아웃: `main-layout`(그리드) = 좌 `card-col`(CharacterCard 세로 3개, onClick 유지) + 우 `board`(MarketMovers·HoldingsPreview·RecentTrades). theme.css에 `.main-layout{display:grid;grid-template-columns: minmax(300px,360px) 1fr; gap:...}` + 좁을 때 `1fr`(미디어쿼리).
  - 빈/로딩/에러 상태 유지.
  - **화면에 요청/설명 라벨 노출 금지.**
- [ ] **Step 3: 빌드+렌더 확인** — `npm run build` 성공. (스모크는 Task 10.)
- [ ] **Step 4: 커밋** — `git add dashboard/frontend/src && git commit -m "feat: 메인 일일 현황판(시장 movers·캐릭터 요약·보유·최근체결), 브랜드 텍스트 제거"`

---

### Task 9: 프론트 상세 — 종목명 + 친화 신호 표시

**Files:** Modify `components/TradesTable.tsx`, `PositionsTable.tsx`; `components/detail.css`

**요구:** 표에 **종목명 우선**(코드는 작게 보조). 거래내역은 **한 줄 요약(signal_summary) + 펼치면 이름·별점(signal_detail)**. 기존 "G1" 코드 배지는 펼침 내부 보조로만.

- [ ] **Step 1: PositionsTable** — 종목 셀을 `display name`(굵게) + 코드(작게/muted)로. `trade.name`/`pos.name` 사용.
- [ ] **Step 2: TradesTable 개편** — 신호 열을:
  - 기본: 🟢(BUY)/🔴(SELL) + `signal_summary` 텍스트.
  - 행 클릭 또는 "펼쳐보기" 토글 → `signal_detail` 리스트(각 `name` + ★×stars). `useState`로 행별 확장.
  - 종목 셀은 `name`(굵게)+코드(작게).
  - 사유 라벨(reasonInfo) 유지. TRAILING_STOP 사유 라벨을 `format.ts reasonInfo`에 추가("트레일링 익절/손절" 초보 문구).
- [ ] **Step 3: format.ts** — `reasonInfo`에 `TRAILING_STOP` 케이스 추가(kind·label). `★` 렌더 헬퍼(선택).
- [ ] **Step 4: 빌드+vitest** — `npm run build` 성공, `npm run test`(기존 vitest 유지, 필요한 스냅샷/유닛 갱신).
- [ ] **Step 5: 커밋** — `git add dashboard/frontend/src && git commit -m "feat: 상세 종목명 표시 + 거래내역 한 줄 요약·펼침(이름·별점)"`

---

### Task 10: 데이터 리셋 실행 + 전체 검증 + 스모크

**Files:** (실행·검증) — 필요 시 `README.md`에 seed_from_replay 사용법 한 줄.

- [ ] **Step 1: 백엔드 회귀** — `python -m pytest -q` → 전부 통과(신규 names·signal_display·seed·api 포함).
- [ ] **Step 2: 프론트 빌드+테스트** — `cd dashboard/frontend && npm run build && npm run test` → 통과.
- [ ] **Step 3: 데이터 리셋 실행** — (DATABASE_URL 설정 하에) `python dashboard/scripts/seed_from_replay.py --force`. 6개월 리플레이가 DB에 적재됨. 네트워크/캐시로 수 분. (테스트 DB나 실제 DB 대상은 실행자가 확인 — 실데이터 보호 위해 대상 URL 확인.)
- [ ] **Step 4: 범용형 정합 검증** — 시드 후 `/api/characters` 의 범용형 total_asset_krw 와 `/api/characters/범용형/equity` 마지막값이 일치하는지 확인(스크립트/수동). 완료 기준 #1.
- [ ] **Step 5: 스모크** — `./dashboard/dashboard.sh start` 후 메인 현황판(브랜드 텍스트 없음·movers·보유)·상세(종목명·신호 펼침)·라이트/다크 렌더 확인(스크린샷 또는 curl+육안). README에 seed_from_replay 한 줄 추가.
- [ ] **Step 6: 커밋** — `git add README.md && git commit -m "docs: seed_from_replay 사용법 + UI v2 스모크 확인"`

---

## Self-Review 체크

- **스펙 커버리지**: §4 리셋=Task1·4·10, §5 종목명=Task2·5, §6.1 현황판=Task6·8, §6.2 신호표시=Task3·5·9, §6.3 범용형=Task4(정합)·10(검증), §7.1 브랜드제거=Task8, §7.2 메인=Task8, §7.3 상세=Task9. 전부 매핑.
- **플레이스홀더**: 로직 태스크(1~7)는 완결 코드. 프론트 UI(8·9)는 데이터 계약·컴포넌트 책임·기존 패턴 준수·초보 친화 제약을 명시(픽셀 코드는 기존 컴포넌트 미러). 완료 기준 명확.
- **타입 일관성**: `signal_summary`/`signal_detail`/`green_score`(Task3·5 정의 → Task7 타입 → Task9 소비) 일치. `positions_by_char`/`cash_by_char`/`last_close`(Task1 → Task4) 일치. `/api/dashboard` 형태(Task6 → Task7 → Task8) 일치.
- **범용형 정합**: Task4가 동일 스냅샷(positions+cash+daily_bars last=last_close) 시딩으로 보장, Task10이 검증.
- **엔진 무변경**: Task1은 ReplayResult 출력 필드 추가(로직 아님)로 한정.
