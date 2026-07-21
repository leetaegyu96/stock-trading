# 장중 자동매매 루프 (Intraday Trading Loop) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 24시간 라이브 페이퍼 서버가 장중 10분마다 유니버스를 스캔해, 기존+신규 신호와 체결강도로 자동 매수·매도하고 킬스위치·휩쏘 가드를 적용한다.

**Architecture:** 엔진에 관찰이 아니라 **행동**하는 `evaluate_intraday`를 추가하되, 매수/매도 판정은 `evaluate_close`와 동일 규칙을 재사용하고 대기열 대신 **현재가 즉시 체결**한다. 오케스트레이터가 유니버스 현재가+당일 누적거래량(+KR 체결강도)을 모아 **잠정 일봉 프레임**을 만들어 넘긴다. 전 경로는 `intraday_enabled` 플래그로 격리 — OFF면 기존 동작·리플레이 등가성·전체 pytest가 100% 불변.

**Tech Stack:** Python 3.11(pandas·SQLAlchemy·pytest), APScheduler, FastAPI, KIS REST.

**스펙:** `docs/superpowers/specs/2026-07-20-intraday-trading-loop-design.md`

## Global Constraints

- **플래그 격리**: `Config.rules.intraday_enabled` 기본 `False`. OFF면 신규 경로에 진입하지 않으며 기존 엔진·리플레이·동치성·전체 pytest가 무수정 통과해야 한다 — 회귀 증거.
- **비용 정직성**: 장중 체결도 기존 `_buy`/`_sell`(수수료·세금·FX 수수료·슬리피지)을 그대로 경유한다. 새 체결 경로를 만들지 않는다.
- **PAPER 전용**: 실주문 코드 없음. KIS는 시세/호가 조회만.
- **부분 실패 스킵**: 시세·호가 조회 실패 종목은 이번 틱 스킵·다음 틱 재시도. 데이터 없는 조건(US 체결강도)은 그 조건만 스킵하고 나머지 신호로 판단.
- **휩쏘/안전 파라미터(정확값)**: 종목당 하루 매수 ≤ 3, 매도 ≤ 3(손절/트레일/강제청산은 예외), 재매수 쿨다운 30분, 킬스위치 당일 손익 ≤ −5%면 신규 매수 중단(매도는 계속).
- **캐릭터 이름**: 국내형/해외형/범용형. 커밋 한국어+타입 접두어.
- 스키마 신설 시 create_all/`--force` 재시딩 관행.

---

### Task 1: 신규 지표 — 가격괴리율·지지/저항선

**Files:**
- Modify: `simcore/indicators.py`
- Test: `tests/test_indicators.py`

**Interfaces — Produces:**
- `indicators.disparity(close: pd.Series, period: int) -> pd.Series` — `(close − SMA(period)) / SMA(period)`. 워밍업 구간은 NaN.
- `indicators.support_resistance(high: pd.Series, low: pd.Series, close: pd.Series, lookback: int) -> tuple[pd.Series, pd.Series]` — `(support, resistance)`. 각 시점 `support` = 직전 `lookback` 구간 최저가(현재 봉 제외), `resistance` = 직전 `lookback` 구간 최고가(현재 봉 제외). 데이터 부족 구간 NaN.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_indicators.py`에 추가

```python
import numpy as np
import pandas as pd
from simcore import indicators as ind


def test_disparity_matches_manual():
    close = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])
    out = ind.disparity(close, period=3)
    # 마지막 시점 SMA(3) = (12+13+14)/3 = 13.0, 괴리율 = (14-13)/13
    assert out.iloc[-1] == (14.0 - 13.0) / 13.0
    assert np.isnan(out.iloc[0])  # 워밍업


def test_support_resistance_prev_window_excludes_current():
    high = pd.Series([10.0, 12.0, 11.0, 15.0, 9.0])
    low = pd.Series([5.0, 6.0, 4.0, 7.0, 3.0])
    close = pd.Series([8.0, 9.0, 8.5, 12.0, 6.0])
    sup, res = ind.support_resistance(high, low, close, lookback=3)
    # index 3 기준 직전 3봉(0,1,2): 최고 high=12, 최저 low=4
    assert res.iloc[3] == 12.0
    assert sup.iloc[3] == 4.0
    assert np.isnan(sup.iloc[0])
```

- [ ] **Step 2: 실패 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/test_indicators.py::test_disparity_matches_manual tests/test_indicators.py::test_support_resistance_prev_window_excludes_current -v`
Expected: FAIL (`AttributeError: module 'simcore.indicators' has no attribute 'disparity'`)

- [ ] **Step 3: 구현 추가** — `simcore/indicators.py` 말미에

```python
def disparity(close: pd.Series, period: int) -> pd.Series:
    """가격괴리율 = (종가 − 이동평균) / 이동평균. 워밍업 구간 NaN."""
    ma = sma(close, period)
    return (close - ma) / ma


def support_resistance(high: pd.Series, low: pd.Series, close: pd.Series,
                       lookback: int) -> tuple[pd.Series, pd.Series]:
    """직전 lookback 구간(현재 봉 제외) 최저가=지지, 최고가=저항."""
    support = low.shift(1).rolling(lookback).min()
    resistance = high.shift(1).rolling(lookback).max()
    return support, resistance
```

- [ ] **Step 4: 통과 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/test_indicators.py -v`
Expected: PASS (기존 지표 테스트 포함 전부)

- [ ] **Step 5: 커밋**

```bash
git add simcore/indicators.py tests/test_indicators.py
git commit -m "feat: 가격괴리율·지지저항선 지표 추가"
```

---

### Task 2: config — 인트라데이 파라미터

**Files:**
- Modify: `simcore/config.py` (`TradeRules` 데이터클래스, 위 Task에서 확인한 필드 뒤에 추가)
- Test: `tests/test_config.py`

**Interfaces — Produces (모두 `Config().rules.<name>`):**
- `intraday_enabled: bool = False`
- `intraday_scan_minutes: int = 10`
- `intraday_max_buys_per_symbol: int = 3`
- `intraday_max_sells_per_symbol: int = 3`
- `intraday_reentry_cooldown_min: int = 30`
- `intraday_daily_loss_halt_pct: float = -0.05`
- `intraday_disparity_period: int = 20`
- `intraday_sr_lookback: int = 20`
- `intraday_strength_buy_min: float = 100.0` (체결강도 매수 임계; KR 체결강도는 100 기준 매수우위 >100)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_config.py`에 추가

```python
from simcore.config import Config


def test_intraday_defaults_off_and_conservative():
    r = Config().rules
    assert r.intraday_enabled is False
    assert r.intraday_scan_minutes == 10
    assert r.intraday_max_buys_per_symbol == 3
    assert r.intraday_max_sells_per_symbol == 3
    assert r.intraday_reentry_cooldown_min == 30
    assert r.intraday_daily_loss_halt_pct == -0.05
    assert r.intraday_disparity_period == 20
    assert r.intraday_sr_lookback == 20
    assert r.intraday_strength_buy_min == 100.0
```

- [ ] **Step 2: 실패 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/test_config.py::test_intraday_defaults_off_and_conservative -v`
Expected: FAIL (`AttributeError: ... 'intraday_enabled'`)

- [ ] **Step 3: 구현** — `simcore/config.py`의 `TradeRules`에 `bear_guard_characters` 필드 **앞** 줄들 뒤(dataclass 필드 영역)에 추가

```python
    # ── 장중 자동매매(인트라데이) — 기본 OFF, OFF면 기존 동작 100% 불변 ──
    intraday_enabled: bool = False
    intraday_scan_minutes: int = 10
    intraday_max_buys_per_symbol: int = 3
    intraday_max_sells_per_symbol: int = 3
    intraday_reentry_cooldown_min: int = 30
    intraday_daily_loss_halt_pct: float = -0.05
    intraday_disparity_period: int = 20
    intraday_sr_lookback: int = 20
    intraday_strength_buy_min: float = 100.0
```

주의: `bear_guard_characters: frozenset = frozenset()`는 기본값 있는 필드이므로, 새 필드도 전부 기본값이 있어 dataclass 필드 순서 규칙(기본값 필드끼리)에 위배되지 않는다. `bear_guard_characters` 위/아래 어디든 무방하나 위 블록은 그 앞에 둔다.

- [ ] **Step 4: 통과 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add simcore/config.py tests/test_config.py
git commit -m "feat: 인트라데이 config 파라미터(플래그·주기·휩쏘·킬스위치)"
```

---

### Task 3: DecisionType — 장중 태그

**Files:**
- Modify: `simcore/models.py` (`DecisionType` enum, 현재 `BUY/PARTIAL_SELL/FULL_SELL/FORCED_SELL`)
- Test: `tests/test_models.py`

**Interfaces — Produces:**
- `DecisionType.INTRADAY_BUY = "INTRADAY_BUY"`, `DecisionType.INTRADAY_SELL = "INTRADAY_SELL"`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_models.py`에 추가

```python
from simcore.models import DecisionType


def test_intraday_decision_types_exist():
    assert DecisionType.INTRADAY_BUY.value == "INTRADAY_BUY"
    assert DecisionType.INTRADAY_SELL.value == "INTRADAY_SELL"
```

- [ ] **Step 2: 실패 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/test_models.py::test_intraday_decision_types_exist -v`
Expected: FAIL (`AttributeError: INTRADAY_BUY`)

- [ ] **Step 3: 구현** — `DecisionType`에 두 값 추가 (`FORCED_SELL` 다음 줄)

```python
    INTRADAY_BUY = "INTRADAY_BUY"
    INTRADAY_SELL = "INTRADAY_SELL"
```

- [ ] **Step 4: 통과 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add simcore/models.py tests/test_models.py
git commit -m "feat: 장중 체결 구분용 DecisionType(INTRADAY_BUY/SELL)"
```

---

### Task 4: 엔진 장중 가드 헬퍼 (휩쏘 캡·재매수 쿨다운·킬스위치)

엔진에 장중 판정용 순수 헬퍼와 상태를 추가한다. **행동(체결)은 Task 5**에서 하고, 여기서는 "이 종목을 지금 매수/매도해도 되는가?"를 판정하는 게이트만 만든다.

**Files:**
- Modify: `simcore/engine.py` (`CharacterState`에 상태 필드 추가, `Engine`에 헬퍼 메서드)
- Test: `tests/test_engine_intraday.py` (신규)

**Interfaces — Consumes:** `Config().rules.intraday_*` (Task 2).

**Interfaces — Produces:**
- `CharacterState` 신규 필드(전부 기본값):
  `intraday_day: "date | None" = None`,
  `intraday_buys: dict = {}`(symbol→int), `intraday_sells: dict = {}`(symbol→int),
  `intraday_last_sell_ts: dict = {}`(symbol→datetime), `intraday_day_start_equity: "float | None" = None`.
- `Engine._intraday_roll_day(st, d: Date, day_equity: float) -> None` — `st.intraday_day != d`면 카운트·쿨다운·타임스탬프 초기화하고 `intraday_day=d`, `intraday_day_start_equity=day_equity` 설정.
- `Engine._intraday_can_buy(st, symbol: str, now: datetime, cur_equity: float) -> bool` — 아래 전부 만족 시 True: 매수 카운트 < `intraday_max_buys_per_symbol`; 재매수 쿨다운 경과(`intraday_last_sell_ts`에서 `intraday_reentry_cooldown_min`분 지남 또는 기록 없음); 킬스위치 미발동(`cur_equity / st.intraday_day_start_equity - 1 > intraday_daily_loss_halt_pct`).
- `Engine._intraday_can_sell(st, symbol: str) -> bool` — 매도 카운트 < `intraday_max_sells_per_symbol`. (손절/트레일/강제는 이 게이트를 거치지 않는다.)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_engine_intraday.py` 신규

```python
from datetime import date, datetime, timedelta
from simcore.config import Config
from simcore.engine import Engine


def _fresh():
    eng = Engine(Config())
    eng.start(date(2026, 7, 20), fx_rate=1300.0)
    return eng


def test_roll_day_resets_counts_and_sets_start_equity():
    eng = _fresh()
    st = next(iter(eng.states.values()))
    st.intraday_buys["AAPL"] = 3
    eng._intraday_roll_day(st, date(2026, 7, 21), day_equity=1_000.0)
    assert st.intraday_day == date(2026, 7, 21)
    assert st.intraday_buys == {}
    assert st.intraday_day_start_equity == 1_000.0


def test_can_buy_respects_daily_cap():
    eng = _fresh()
    st = next(iter(eng.states.values()))
    eng._intraday_roll_day(st, date(2026, 7, 20), day_equity=1_000.0)
    now = datetime(2026, 7, 20, 10, 0, 0)
    st.intraday_buys["AAPL"] = 3  # cap=3 소진
    assert eng._intraday_can_buy(st, "AAPL", now, cur_equity=1_000.0) is False
    st.intraday_buys["AAPL"] = 2
    assert eng._intraday_can_buy(st, "AAPL", now, cur_equity=1_000.0) is True


def test_can_buy_respects_reentry_cooldown():
    eng = _fresh()
    st = next(iter(eng.states.values()))
    eng._intraday_roll_day(st, date(2026, 7, 20), day_equity=1_000.0)
    sold_at = datetime(2026, 7, 20, 10, 0, 0)
    st.intraday_last_sell_ts["AAPL"] = sold_at
    # 쿨다운 30분: 20분 뒤 불가, 31분 뒤 가능
    assert eng._intraday_can_buy(st, "AAPL", sold_at + timedelta(minutes=20),
                                 cur_equity=1_000.0) is False
    assert eng._intraday_can_buy(st, "AAPL", sold_at + timedelta(minutes=31),
                                 cur_equity=1_000.0) is True


def test_can_buy_killswitch_blocks_when_daily_loss_exceeds():
    eng = _fresh()
    st = next(iter(eng.states.values()))
    eng._intraday_roll_day(st, date(2026, 7, 20), day_equity=1_000.0)
    now = datetime(2026, 7, 20, 13, 0, 0)
    # -5% 초과 손실(-6%): 매수 중단
    assert eng._intraday_can_buy(st, "AAPL", now, cur_equity=940.0) is False
    # -4% 손실: 매수 허용
    assert eng._intraday_can_buy(st, "AAPL", now, cur_equity=960.0) is True


def test_can_sell_respects_daily_cap():
    eng = _fresh()
    st = next(iter(eng.states.values()))
    eng._intraday_roll_day(st, date(2026, 7, 20), day_equity=1_000.0)
    st.intraday_sells["AAPL"] = 3
    assert eng._intraday_can_sell(st, "AAPL") is False
    st.intraday_sells["AAPL"] = 1
    assert eng._intraday_can_sell(st, "AAPL") is True
```

- [ ] **Step 2: 실패 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/test_engine_intraday.py -v`
Expected: FAIL (`AttributeError: '_intraday_roll_day'` 등)

- [ ] **Step 3: CharacterState 필드 추가** — `simcore/engine.py`의 `CharacterState`(현재 `pending_buys`/`pending_sells`/`cooldowns` 필드가 있는 dataclass)에 추가

```python
    intraday_day: "date | None" = None
    intraday_buys: dict = field(default_factory=dict)
    intraday_sells: dict = field(default_factory=dict)
    intraday_last_sell_ts: dict = field(default_factory=dict)
    intraday_day_start_equity: "float | None" = None
```

(파일 상단 import에 `from datetime import datetime`이 없으면 추가. `date`·`field`는 기존 사용 중.)

- [ ] **Step 4: 헬퍼 메서드 추가** — `Engine`에 `check_stops` 근처에 추가

```python
    def _intraday_roll_day(self, st, d, day_equity: float) -> None:
        if st.intraday_day != d:
            st.intraday_day = d
            st.intraday_buys = {}
            st.intraday_sells = {}
            st.intraday_last_sell_ts = {}
            st.intraday_day_start_equity = day_equity

    def _intraday_can_buy(self, st, symbol, now, cur_equity: float) -> bool:
        r = self.config.rules
        if st.intraday_buys.get(symbol, 0) >= r.intraday_max_buys_per_symbol:
            return False
        last = st.intraday_last_sell_ts.get(symbol)
        if last is not None:
            mins = (now - last).total_seconds() / 60.0
            if mins < r.intraday_reentry_cooldown_min:
                return False
        start = st.intraday_day_start_equity
        if start and (cur_equity / start - 1.0) <= r.intraday_daily_loss_halt_pct:
            return False   # 킬스위치: 당일 손실 한도 도달 → 신규 매수 중단
        return True

    def _intraday_can_sell(self, st, symbol) -> bool:
        return st.intraday_sells.get(symbol, 0) < self.config.rules.intraday_max_sells_per_symbol
```

- [ ] **Step 5: 통과 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/test_engine_intraday.py -v`
Expected: PASS

- [ ] **Step 6: 회귀 확인 (플래그 OFF 불변)**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/ -q`
Expected: 기존 전부 PASS (신규 필드는 기본값이라 기존 동작 불변)

- [ ] **Step 7: 커밋**

```bash
git add simcore/engine.py tests/test_engine_intraday.py
git commit -m "feat: 엔진 장중 가드(휩쏘 캡·재매수 쿨다운·킬스위치)"
```

---

### Task 5: 엔진 `evaluate_intraday` — 현재가 즉시 체결

`evaluate_close`의 매수/매도 **판정 규칙을 재사용**하되, 대기열이 아니라 즉시 `_buy`/`_sell`로 현재가 체결한다. 체결강도 오버레이·Task 4 게이트를 적용한다.

**Files:**
- Modify: `simcore/engine.py`
- Test: `tests/test_engine_intraday.py`

**Interfaces — Consumes:** Task 4 헬퍼, `_buy`/`_sell`(기존), `SymbolSnapshot`(기존), `DecisionType.INTRADAY_BUY/SELL`(Task 3).

**Interfaces — Produces:**
- `Engine.evaluate_intraday(d: Date, market: Market, snaps: dict[str, SymbolSnapshot], strengths: dict[str, "float | None"], fx_rate: float, now: datetime, day_equity: dict[str, float], cur_equity: dict[str, float]) -> None`
  - `snaps`: 종목→잠정봉 기반 SymbolSnapshot(Task 6이 구성).
  - `strengths`: 종목→체결강도(없으면 None → 매수 임계 조건 스킵).
  - `day_equity`/`cur_equity`: 캐릭터명→해당 시각 자산(킬스위치·roll_day용, Task 6이 계산해 전달).
  - 동작: 각 캐릭터에 `_intraday_roll_day` 호출 → **매도**(보유 종목이 매도 규칙 발동 & `_intraday_can_sell` → `_sell(..., decision_type=INTRADAY_SELL)`, 매도 카운트++·`intraday_last_sell_ts` 기록) → **매수**(미보유 & 게이트 통과 & 체결강도 조건 & `_intraday_can_buy` & 슬롯 여유 → `_buy(...)`, 매수 카운트++). 손절/트레일은 이 메서드가 관여하지 않는다(별도 `check_stops` 유지).
  - 매도 규칙은 `evaluate_close`와 동일: `red_score >= sell_full_min`(전량) / `>= sell_partial_min`(부분) / 강제(R18·R5+R23). 강제 매도는 `_intraday_can_sell` 게이트를 우회(리스크 축소 우선).
  - 체결강도 조건: `strengths.get(sym)`가 None이면 통과, 값 있으면 `>= intraday_strength_buy_min`일 때만 매수.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_engine_intraday.py`에 추가

```python
from simcore.models import Market, SymbolSnapshot, DecisionType


def _buy_snap(sym, gscore):
    # 게이트 통과 + 점수 충분한 매수 후보 스냅
    return SymbolSnapshot(sym, Market.KR, green=("G1",) * 3, red=(),
                          close=10000.0, change_pct=0.01, volume=1000.0,
                          green_score=gscore, red_score=0, buy_gate=True)


def test_intraday_buys_at_current_price_and_counts():
    eng = _fresh()
    name = "국내형"
    st = eng.states[name]
    now = datetime(2026, 7, 20, 10, 0, 0)
    snaps = {"005930": _buy_snap("005930", eng.config.rules.buy_score_min + 5)}
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, snaps,
                          strengths={"005930": 150.0}, fx_rate=1300.0, now=now,
                          day_equity={name: 1e8}, cur_equity={name: 1e8})
    assert "005930" in st.portfolio.positions          # 즉시 체결됨
    assert st.intraday_buys.get("005930") == 1
    # 체결 거래의 decision_type 태그 확인
    last_trade = st.portfolio.trades[-1]
    assert last_trade.decision_type == DecisionType.INTRADAY_BUY


def test_intraday_buy_blocked_when_strength_below_min():
    eng = _fresh()
    name = "국내형"
    now = datetime(2026, 7, 20, 10, 0, 0)
    snaps = {"005930": _buy_snap("005930", eng.config.rules.buy_score_min + 5)}
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, snaps,
                          strengths={"005930": 80.0}, fx_rate=1300.0, now=now,
                          day_equity={name: 1e8}, cur_equity={name: 1e8})
    assert "005930" not in eng.states[name].portfolio.positions  # 체결강도 미달 차단


def test_intraday_buy_allowed_when_strength_none():
    eng = _fresh()
    name = "국내형"
    now = datetime(2026, 7, 20, 10, 0, 0)
    snaps = {"005930": _buy_snap("005930", eng.config.rules.buy_score_min + 5)}
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, snaps,
                          strengths={"005930": None}, fx_rate=1300.0, now=now,
                          day_equity={name: 1e8}, cur_equity={name: 1e8})
    assert "005930" in eng.states[name].portfolio.positions  # None이면 조건 스킵 → 체결
```

- [ ] **Step 2: 실패 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/test_engine_intraday.py -k intraday_buy -v`
Expected: FAIL (`AttributeError: 'evaluate_intraday'`)

- [ ] **Step 3: 구현** — `simcore/engine.py`에 `evaluate_intraday` 추가 (Task 4 헬퍼 아래)

```python
    def evaluate_intraday(self, d, market, snaps, strengths, fx_rate, now,
                          day_equity, cur_equity):
        r = self.config.rules
        for st in self.states.values():
            if market not in st.spec.markets:
                continue
            self._intraday_roll_day(st, d, day_equity.get(st.spec.name, 0.0))
            eq = cur_equity.get(st.spec.name, st.intraday_day_start_equity or 0.0)
            # 1) 매도 (보유 종목 규칙 발동 시 현재가 즉시 매도)
            for sym in list(st.portfolio.positions):
                pos = st.portfolio.positions[sym]
                if pos.market != market or sym not in snaps:
                    continue
                s = snaps[sym]
                red = set(s.red)
                forced = ("R18" in red or ({"R5", "R23"} <= red))
                if forced:
                    trig = "R18" if "R18" in red else "R5+R23"
                    self._sell(st, d, sym, s.close, TradeReason.SIGNAL_SELL, fx_rate,
                               red_count=len(red), red_score=s.red_score, fired=tuple(s.red),
                               decision_type=DecisionType.INTRADAY_SELL, trigger_rule=trig)
                    st.intraday_sells[sym] = st.intraday_sells.get(sym, 0) + 1
                    st.intraday_last_sell_ts[sym] = now
                    continue
                full = s.red_score >= r.sell_full_min
                partial = s.red_score >= r.sell_partial_min
                if (full or partial) and self._intraday_can_sell(st, sym):
                    qty = (max(1, int(pos.quantity * r.partial_sell_fraction))
                           if partial and not full else None)
                    self._sell(st, d, sym, s.close, TradeReason.SIGNAL_SELL, fx_rate,
                               quantity=qty, red_count=len(red), red_score=s.red_score,
                               fired=tuple(s.red), decision_type=DecisionType.INTRADAY_SELL,
                               trigger_rule="+".join(s.red))
                    st.intraday_sells[sym] = st.intraday_sells.get(sym, 0) + 1
                    if sym not in st.portfolio.positions:
                        st.intraday_last_sell_ts[sym] = now
            # 2) 매수 (미보유 종목이 게이트+조건 충족 시 현재가 즉시 매수)
            held = set(st.portfolio.positions)
            cands = sorted(
                (s for sym, s in snaps.items()
                 if sym not in held and sym not in st.cooldowns
                 and s.green_score >= r.buy_score_min and s.buy_gate),
                key=lambda s: (-s.green_score, -s.change_pct, -s.volume))
            for s in cands:
                slots = r.max_positions - len(st.portfolio.positions)
                if slots <= 0:
                    break
                strength = strengths.get(s.symbol)
                if strength is not None and strength < r.intraday_strength_buy_min:
                    continue
                if not self._intraday_can_buy(st, s.symbol, now, eq):
                    continue
                b = PendingBuy(s.symbol, market, len(s.green), s.green_score, s.green,
                               s.change_pct, s.volume,
                               decision_type=DecisionType.INTRADAY_BUY,
                               trigger_rule=f"장중 게이트+{s.green_score}점")
                if self._buy(st, d, b, s.close, fx_rate, slots):
                    st.intraday_buys[s.symbol] = st.intraday_buys.get(s.symbol, 0) + 1
```

- [ ] **Step 4: 통과 확인 (장중 매수 3종)**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/test_engine_intraday.py -v`
Expected: PASS

- [ ] **Step 5: 매도·캡 통합 테스트 추가**

```python
def test_intraday_sell_full_on_high_red_and_caps():
    eng = _fresh()
    name = "국내형"
    st = eng.states[name]
    now = datetime(2026, 7, 20, 10, 0, 0)
    # 먼저 보유 만들기(매수)
    buy = {"005930": _buy_snap("005930", eng.config.rules.buy_score_min + 5)}
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, buy, {"005930": None},
                          1300.0, now, {name: 1e8}, {name: 1e8})
    assert "005930" in st.portfolio.positions
    # 적신호 급증 스냅으로 전량매도 유발
    sell_snap = SymbolSnapshot("005930", Market.KR, green=(), red=("R1",) * 12,
                               close=9000.0, change_pct=-0.1, volume=2000.0,
                               green_score=0, red_score=eng.config.rules.sell_full_min,
                               buy_gate=False)
    eng.evaluate_intraday(date(2026, 7, 20), Market.KR, {"005930": sell_snap},
                          {"005930": None}, 1300.0,
                          now + timedelta(minutes=10), {name: 1e8}, {name: 1e8})
    assert "005930" not in st.portfolio.positions
    assert st.intraday_sells.get("005930") == 1
    assert st.portfolio.trades[-1].decision_type == DecisionType.INTRADAY_SELL
```

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/test_engine_intraday.py::test_intraday_sell_full_on_high_red_and_caps -v`
Expected: PASS

- [ ] **Step 6: 회귀 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/ -q`
Expected: 기존 전부 PASS(`evaluate_intraday`는 호출되기 전엔 무영향)

- [ ] **Step 7: 커밋**

```bash
git add simcore/engine.py tests/test_engine_intraday.py
git commit -m "feat: 엔진 evaluate_intraday(현재가 즉시 체결·체결강도 게이팅)"
```

---

### Task 6: KIS 체결강도 조회

**Files:**
- Modify: `simcore/live/kis_client.py`
- Test: `tests/live/test_kis_client.py` (없으면 신규)

**Interfaces — Produces:**
- `KisClient.execution_strength(market: str, symbol: str) -> "float | None"` — KR: `inquire-price` 응답의 체결강도 필드(`tr_id` `FHKST01010100`, 응답 `output.tshprc`가 아니라 체결강도 필드 `output` 내 `"tsbp"`/`"cttr"` 계열; 실제 필드명은 KIS 문서상 **체결강도=`"cttr"`**)를 float로 반환. US(`market == "US"`): 미지원 → `None`. 파싱 실패·키 없음 → `None`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/live/test_kis_client.py`에 추가. KIS 실호출 금지 → `_get`을 monkeypatch로 대체.

```python
from simcore.live.kis_client import KisClient


def _client_with_stub(monkeypatch, payload):
    c = KisClient.__new__(KisClient)  # __init__ 우회(네트워크·토큰 없음)
    monkeypatch.setattr(c, "_get", lambda path, tr_id, params: payload)
    return c


def test_execution_strength_kr_parses_cttr(monkeypatch):
    c = _client_with_stub(monkeypatch, {"output": {"cttr": "123.45"}})
    assert c.execution_strength("KR", "005930") == 123.45


def test_execution_strength_us_returns_none(monkeypatch):
    c = _client_with_stub(monkeypatch, {"output": {"cttr": "123.45"}})
    assert c.execution_strength("US", "AAPL") is None


def test_execution_strength_missing_field_returns_none(monkeypatch):
    c = _client_with_stub(monkeypatch, {"output": {}})
    assert c.execution_strength("KR", "005930") is None
```

- [ ] **Step 2: 실패 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/live/test_kis_client.py -k execution_strength -v`
Expected: FAIL (`AttributeError: 'execution_strength'`)

- [ ] **Step 3: 구현** — `simcore/live/kis_client.py`의 `current_price` 근처에 추가

```python
    def execution_strength(self, market: str, symbol: str):
        """체결강도(매수/매도 체결 비율, 100 기준). KR 만 지원, US 는 None.
        조회·파싱 실패 시 None(호출부가 이 조건을 스킵)."""
        if market != "KR":
            return None
        try:
            j = self._get("/uapi/domestic-stock/v1/quotations/inquire-price",
                           "FHKST01010100",
                           {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol})
            raw = j.get("output", {}).get("cttr")
            return float(raw) if raw not in (None, "") else None
        except Exception:
            return None
```

- [ ] **Step 4: 통과 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/live/test_kis_client.py -k execution_strength -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add simcore/live/kis_client.py tests/live/test_kis_client.py
git commit -m "feat: KIS 체결강도 조회(KR 지원·US None)"
```

---

### Task 7: 오케스트레이터 `on_intraday` — 잠정봉 구성·평가·영속

**Files:**
- Modify: `simcore/live/orchestrator.py`
- Test: `tests/live/test_orchestrator.py`

**Interfaces — Consumes:** `Engine.evaluate_intraday`(Task 5), `KisClient.execution_strength`(Task 6), `evaluate_frame`/`fired_at`/`snapshot_scores`(기존), `SymbolSnapshot`(기존).

**Interfaces — Produces:**
- 오케스트레이터 상태 `self._intraday_hl: dict[str, tuple]`(symbol→(open, high, low, day)) — 당일 시가·장중 고저 추적, 일자 바뀌면 리셋.
- `Orchestrator.on_intraday(now: datetime, d: date, market: str, universe: list[str]) -> None`
  - 각 종목: 현재가+당일 누적거래량 조회(`current_price`, 그리고 KR은 `execution_strength`). 실패 스킵.
  - 확정 일봉 히스토리(어제까지, `_refresh_bars`가 반환하는 df에서 오늘 행 제외/치환) + **잠정 오늘 봉**(open=당일 첫 관측가, high/low=`_intraday_hl` 갱신 최고/최저, close=현재가, volume=당일 누적) append → `evaluate_frame` → `fired_at` → `snapshot_scores` → `SymbolSnapshot` 구성.
  - `day_equity`/`cur_equity`: 각 캐릭터 자산을 `engine.snapshot(self._last_price, fx)`로 계산(당일 시작분은 엔진의 `intraday_day_start_equity`가 roll_day에서 세팅되므로 `day_equity`엔 현재 계산치를 넘겨도 roll 시점에만 반영됨 — 첫 틱에서 그날 시작자산으로 고정).
  - `engine.evaluate_intraday(...)` 호출 → 트랜잭션으로 `persist_state`+`append_new_trades`(기존 `on_tick` 패턴 동일).

주의: 현재가 조회 응답에서 당일 누적거래량을 얻으려면 `current_price`가 종가만 반환하므로, 누적량은 `_get` 원응답 필드(`acml_vol`)가 필요하다. 이 Task에서 `current_price`를 바꾸지 말고, 오케스트레이터에서 `kis.daily_bars(market, sym, d, d)`로 당일 행을 받아 `volume`을 취하거나(간단), 조회 실패 시 전일 거래량 대용. **결정: `daily_bars(d,d)`의 당일 volume을 사용하고, 실패 시 히스토리 마지막 거래량 대용.**

- [ ] **Step 1: 실패 테스트 작성** — `tests/live/test_orchestrator.py`에 추가. KIS·repo는 기존 테스트의 페이크 패턴을 따른다(이 파일 상단의 기존 fixture/fake 재사용).

```python
from datetime import datetime, date
from simcore.models import Market


def test_on_intraday_buys_and_persists(intraday_orch_setup):
    """게이트 통과 종목이 장중에 즉시 체결되고 상태가 영속된다."""
    orch, repo, market, sym = intraday_orch_setup   # fixture가 신호=매수 상태로 구성
    now = datetime(2026, 7, 20, 10, 0, 0)
    orch.on_intraday(now, date(2026, 7, 20), market, [sym])
    # 엔진 포지션에 체결 반영
    assert any(sym in st.portfolio.positions for st in orch.engine.states.values())
    # 거래가 DB에 append 되었는지(기존 repo 조회 헬퍼 사용)
    assert repo.recent_trades(limit=5)  # 비어있지 않음
```

주의: `intraday_orch_setup` fixture는 이 파일의 기존 orchestrator 페이크(kis.current_price/daily_bars/execution_strength 스텁, 인메모리 repo, `Config`에 `intraday_enabled=True`)를 조립해 매수 신호가 뜨는 일봉 히스토리를 준비한다. 기존 `on_close` 테스트의 fixture를 복제·확장할 것.

- [ ] **Step 2: 실패 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/live/test_orchestrator.py -k on_intraday -v`
Expected: FAIL (`AttributeError: 'on_intraday'` 또는 fixture 미정의)

- [ ] **Step 3: 구현** — `simcore/live/orchestrator.py`에 `on_tick` 근처로 추가. `__init__`에 `self._intraday_hl = {}` 초기화 추가.

```python
    def on_intraday(self, now, d, market: str, universe: list[str]) -> None:
        m = Market(market)
        fx = self.fx(d)
        snaps = {}
        strengths = {}
        for sym in universe:
            try:
                px = self.kis.current_price(market, sym)
            except Exception:
                continue
            self._last_price[sym] = px
            # 당일 거래량(실패 시 히스토리 마지막 거래량 대용)
            try:
                today = self.kis.daily_bars(market, sym, d, d)
                vol = float(today["volume"].iloc[-1]) if not today.empty else 0.0
            except Exception:
                vol = 0.0
            # 확정 히스토리 + 잠정 오늘 봉
            try:
                df = self._refresh_bars(market, sym, d)
            except Exception as exc:
                print(f"[intraday] {market} {sym} 일봉 실패 스킵: {exc}")
                continue
            o, hi, lo, hl_day = self._intraday_hl.get(sym, (px, px, px, d))
            if hl_day != d:
                o, hi, lo = px, px, px
            hi, lo = max(hi, px), min(lo, px)
            self._intraday_hl[sym] = (o, hi, lo, d)
            ts = pd.Timestamp(d)
            df = df.copy()
            df.loc[ts] = {"open": o, "high": hi, "low": lo, "close": px,
                          "volume": vol if vol else df["volume"].iloc[-1]}
            df = df.sort_index()
            frame = sigmod.evaluate_frame(df, self.cfg.signals)
            green, red = sigmod.fired_at(frame, ts)
            gs, rs, gate = sigmod.snapshot_scores(green, red, self.cfg.scores)
            loc = df.index.get_loc(ts)
            prev_close = float(df["close"].iloc[loc - 1]) if loc > 0 else px
            snaps[sym] = SymbolSnapshot(sym, m, green, red, px, px / prev_close - 1.0,
                                        vol, green_score=gs, red_score=rs, buy_gate=gate)
            strengths[sym] = self.kis.execution_strength(market, sym)
        if not snaps:
            return
        eq = self.engine.snapshot(self._last_price, fx)
        self.engine.evaluate_intraday(d, m, snaps, strengths, fx, now,
                                      day_equity=eq, cur_equity=eq)
        with self.repo.transaction() as s:
            self.repo.persist_state(self.engine, session=s)
            self.repo.append_new_trades(self.engine, session=s)
```

- [ ] **Step 4: 통과 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/live/test_orchestrator.py -k on_intraday -v`
Expected: PASS

- [ ] **Step 5: 회귀 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/ -q`
Expected: 기존 전부 PASS

- [ ] **Step 6: 커밋**

```bash
git add simcore/live/orchestrator.py tests/live/test_orchestrator.py
git commit -m "feat: 오케스트레이터 on_intraday(잠정봉 구성·장중 평가·영속)"
```

---

### Task 8: 스케줄러 — 장중 스캔(장 시간 가드·플래그)

**Files:**
- Modify: `simcore/live/scheduler.py`, `simcore/live/__main__.py`(스케줄러에 cfg 전달)
- Test: `tests/live/test_scheduler.py` (없으면 신규)

**Interfaces — Consumes:** `Orchestrator.on_intraday`(Task 7), `Config.rules.intraday_enabled`/`intraday_scan_minutes`(Task 2).

**Interfaces — Produces:**
- `LiveScheduler.__init__`에 `cfg` 인자 추가(기본 없으면 `Config()`), `intraday_scan_minutes` 반영.
- `LiveScheduler._guarded_intraday(market)` — 거래일 && **장 시간 중**(개장~마감 사이)일 때만 `orch.on_intraday(now, today, market, universe)`. 장 시간 판정은 `_SESSIONS`의 (개장, 마감) 사이.
- `build()`: `cfg.rules.intraday_enabled`가 True일 때만 시장별 `_guarded_intraday` 인터벌 잡 등록(`intraday_scan_minutes` 주기). False면 등록 안 함(기존 open/close/tick만).

- [ ] **Step 1: 실패 테스트 작성** — `tests/live/test_scheduler.py`

```python
from datetime import datetime
from simcore.config import Config
from simcore.live.scheduler import LiveScheduler


class _Orch:
    def __init__(self): self.calls = []
    def on_open(self, *a): pass
    def on_close(self, *a): pass
    def on_tick(self, *a): pass
    def on_intraday(self, now, d, market, universe): self.calls.append((market, now))


def _sched(intraday: bool):
    cfg = Config()
    object.__setattr__(cfg.rules, "intraday_enabled", intraday)  # frozen 우회 불가 시 replace 사용
    return LiveScheduler(_Orch(), repo=None,
                         holidays_provider=lambda m: set(),
                         universe_provider=lambda m: ["005930"], cfg=cfg)


def test_intraday_job_registered_only_when_enabled():
    on = _sched(True).build()
    off = _sched(False).build()
    assert any(j.id.startswith("intraday_") for j in on.get_jobs())
    assert not any(j.id.startswith("intraday_") for j in off.get_jobs())
    on.shutdown(wait=False); off.shutdown(wait=False)
```

주의: `TradeRules`가 frozen dataclass면 `object.__setattr__` 대신 `from dataclasses import replace`로 `replace(cfg.rules, intraday_enabled=True)` 후 `replace(cfg, rules=...)`를 쓴다. 구현 시 실제 frozen 여부 확인 후 테스트를 그에 맞게 작성.

- [ ] **Step 2: 실패 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/live/test_scheduler.py -v`
Expected: FAIL (`TypeError: __init__() got unexpected keyword 'cfg'` 또는 intraday 잡 없음)

- [ ] **Step 3: 구현** — `simcore/live/scheduler.py`

```python
from simcore.config import Config
# __init__ 시그니처에 cfg 추가
    def __init__(self, orch, repo, holidays_provider, universe_provider,
                 tick_minutes=5, cfg=None):
        self.orch = orch
        self.repo = repo
        self.holidays = holidays_provider
        self.universe = universe_provider
        self.tick_minutes = tick_minutes
        self.cfg = cfg or Config()

    def _in_session(self, market: str) -> bool:
        tz, (oh, om), (ch, cm) = _SESSIONS[market]
        nowt = datetime.now(tz).time()
        from datetime import time as _t
        return _t(oh, om) <= nowt <= _t(ch, cm)

    def _guarded_intraday(self, market: str) -> None:
        if self._is_trading_today(market) and self._in_session(market):
            tz = _SESSIONS[market][0]
            self.orch.on_intraday(datetime.now(tz), _today(market), market,
                                  self.universe(market))
```

그리고 `build()`의 시장 루프 안, tick 잡 등록 뒤에:

```python
            if self.cfg.rules.intraday_enabled:
                sched.add_job(self._guarded_intraday,
                              IntervalTrigger(minutes=self.cfg.rules.intraday_scan_minutes),
                              args=[market], id=f"intraday_{market}")
```

`simcore/live/__main__.py`의 `LiveScheduler(...)` 생성부에 `cfg=Config()`(이미 `Config()` 인스턴스가 orch에 있으면 그것)를 전달.

- [ ] **Step 4: 통과 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/live/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 5: 회귀 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/ -q`
Expected: 전부 PASS(기본 OFF라 intraday 잡 미등록)

- [ ] **Step 6: 커밋**

```bash
git add simcore/live/scheduler.py simcore/live/__main__.py tests/live/test_scheduler.py
git commit -m "feat: 스케줄러 장중 스캔 잡(장시간 가드·플래그 게이트)"
```

---

### Task 9: 대시보드 표시 + 문서 + 회귀

**Files:**
- Modify: `dashboard/backend/summary.py` 또는 결정유형 표시 매핑이 있는 곳(기존 `_safe_decision_type`/표시 매핑), `dashboard/frontend/src/`(결정 칩 라벨), `docs/trading-rules.md`
- Test: `tests/dashboard/`, 프론트 vitest

**Interfaces — Consumes:** `DecisionType.INTRADAY_BUY/SELL`(Task 3).

- [ ] **Step 1: 백엔드 표시 매핑 테스트** — 기존 결정유형→한국어 라벨 매핑 테스트가 있는 파일(`tests/dashboard/test_summary.py` 또는 `test_api.py`)에 추가

```python
def test_intraday_decision_labels_present():
    from dashboard.backend import summary
    # 매핑 함수/딕셔너리 이름은 기존 코드에 맞춘다(예: _DECISION_LABEL)
    assert summary._DECISION_LABEL[ "INTRADAY_BUY" ] == "장중 매수"
    assert summary._DECISION_LABEL[ "INTRADAY_SELL" ] == "장중 매도"
```

주의: 실제 매핑 위치/이름은 구현자가 `grep -rn "FORCED_SELL\|강제 전량매도\|decision" dashboard/backend`로 찾아 그 구조에 맞춰 라벨 2개를 추가하고, 테스트를 실제 이름에 맞게 작성한다.

- [ ] **Step 2: 실패 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/dashboard/ -k intraday_decision -v`
Expected: FAIL

- [ ] **Step 3: 백엔드 라벨 추가** — 기존 매핑에 `INTRADAY_BUY→"장중 매수"`, `INTRADAY_SELL→"장중 매도"` 추가.

- [ ] **Step 4: 통과 확인**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/dashboard/ -k intraday_decision -v`
Expected: PASS

- [ ] **Step 5: 프론트 라벨 반영** — 결정유형 칩 매핑(types.ts/포맷 헬퍼)에 두 값의 한국어 라벨·색상 추가. vitest에 "장중 매수/매도" 렌더 단언 1건 추가.

Run: `cd /mnt/c/data/webapp/my/graph/dashboard/frontend && npm run build && npx vitest run`
Expected: build 성공 + 전부 PASS

- [ ] **Step 6: 문서** — `docs/trading-rules.md`에 §17 "장중 자동매매(인트라데이)" 절 추가: 플래그·10분 스캔·잠정봉·신규 지표(괴리율·지지저항)·체결강도(KR 전용)·휩쏘 캡 3회·재매수 쿨다운 30분·킬스위치 −5%·비용 적용·리플레이 미포함. `docs/next-steps.md`의 관련 항목 갱신(인트라데이 착수→진행).

- [ ] **Step 7: 전체 회귀**

Run: `cd /mnt/c/data/webapp/my/graph && python -m pytest tests/ -q && cd dashboard/frontend && npm run build && npx vitest run`
Expected: 백엔드·프론트 전부 PASS

- [ ] **Step 8: 커밋**

```bash
git add -A
git commit -m "feat: 장중 매매 대시보드 라벨·규칙 문서(인트라데이)"
```

---

## 완료 후 (플랜 밖)

- 최종 전체브랜치 리뷰(opus) → dev 병합 → 운영 서버에서 `intraday_enabled=True`로 활성화(별도 설정/환경변수) → 장중 로그로 첫 실동작 관측(매수/매도·킬스위치) → 이상 없으면 v1.10.0(누적분 포함) 릴리즈.
- 후속(별도 스펙): 뉴스·토픽·이슈 외부 정보축(감사 4단계), 분봉 자체 신호 체계.
