# 감사 Phase A — 신뢰 회복 (P0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 엔진의 실제 결정을 데이터로 영속해 화면 설명과 100% 일치시키고(P0-1), 신호 범위를 정직히 고지하며(P0-2), 절대수익률 대신 벤치마크·위험조정 성과를 보여준다(P0-3). 전 화면에 운영 모드·데이터 as-of 고정.

**Architecture:** 엔진은 매수/매도 결정 시점에 `DecisionType`+`trigger_rule`을 확정해 Trade에 영속한다. 표시 계층(signal_display·프론트)은 그 데이터를 문구로 **변환만** 하고 red_score로 재계산하지 않는다 — 이것이 P0-1 모순의 구조적 해소. metrics는 기존 equity/trades로 위험조정 지표를 계산하고, 리플레이/시드가 지수로 벤치마크 초과수익을 산출한다.

**Tech Stack:** Python 3.11(dataclasses·pandas·SQLAlchemy·pytest), React+TS(Vite·vitest), FastAPI.

**스펙:** `docs/superpowers/specs/2026-07-10-audit-phase-a-trust-design.md`
**요구사항 원본:** `docs/reviews/2026-07-10-trading-product-audit.md` (§2 P0, §6 1단계)
**브랜치:** `feature/audit-phase-a-trust` (dev 0e25ec2에서 분기, 스펙 커밋 이후)

## Global Constraints

- 캐릭터 이름 정확히 `국내형`/`해외형`/`범용형`.
- **표시는 결정 데이터를 문구로 변환만** — `signal_display`·프론트는 red_score로 행동 라벨을 재계산하지 않는다(P0-1 핵심).
- `DecisionType` 값: `BUY`, `PARTIAL_SELL`, `FULL_SELL`, `FORCED_SELL`. `trigger_rule`은 문자열(예 `"R5+R23"`, `"R18"`, `"R7"`, `"R10"`, `"게이트+19점"`, 적신호 코드 join).
- 강제매도 원인 → trigger_rule 매핑: 지지선 붕괴=`"R18"`, 급락복합=`"R5+R23"`, 잠금손절=`"R7"`, 트레일링=`"R10"`.
- Trade 신규 필드는 **키워드 생성**(realized_pnl/score 삽입 관행 유지, 위치인자 오프셋 금지).
- 신호 라벨은 프론트에서 **"기술적 매수/매도 신호"**(P0-2). "검증됨" 라벨 **금지**(P0-3).
- 위험조정 지표 무위험수익률=0 가정 명시.
- 커밋: 한국어 + 타입 접두어. 전체 테스트: `pytest tests/ -q`(시작 기준 dev에서 통과, tests/live·dashboard는 DB env로 실행). 프론트: `cd dashboard/frontend && npm run build && npx vitest run`.
- db 스키마 신규 컬럼은 기존 관행(create_all 신규 시; `seed_from_replay --force`가 drop+recreate). 마이그레이션 툴 부재는 기존 관행.

---

### Task 1: DecisionType 모델 + Trade/Pending 필드 + portfolio 배선

**Files:**
- Modify: `simcore/models.py` (TradeReason 아래 DecisionType 추가; Trade에 필드; :57-74)
- Modify: `simcore/engine.py` (PendingBuy·PendingSell에 필드; :35-48)
- Modify: `simcore/portfolio.py` (buy/sell가 decision_type·trigger_rule 전달; :58-100)
- Test: `tests/test_models.py`, `tests/test_portfolio.py`

**Interfaces:**
- Produces: `models.DecisionType(str, Enum)` = {BUY, PARTIAL_SELL, FULL_SELL, FORCED_SELL}. `Trade.decision_type: DecisionType = DecisionType.BUY`, `Trade.trigger_rule: str = ""` (둘 다 realized_pnl 뒤 키워드 필드). `Portfolio.buy(..., decision_type=DecisionType.BUY, trigger_rule="")`, `Portfolio.sell(..., decision_type=DecisionType.FULL_SELL, trigger_rule="")`. `PendingBuy`/`PendingSell`에 `decision_type`·`trigger_rule` 필드.

- [ ] **Step 1: 실패 테스트** — `tests/test_models.py`에 추가:

```python
def test_trade_has_decision_fields():
    from simcore.models import Trade, DecisionType, Market, Side
    from datetime import date
    t = Trade(date(2026,1,2), "국내형", "AAA", Market.KR, Side.SELL, 1, 100.0, 0.0, 0.0,
              __import__("simcore.models", fromlist=["TradeReason"]).TradeReason.SIGNAL_SELL,
              realized_pnl=0.0, decision_type=DecisionType.FORCED_SELL, trigger_rule="R18")
    assert t.decision_type == DecisionType.FORCED_SELL and t.trigger_rule == "R18"
    assert list(DecisionType) and DecisionType.BUY.value == "BUY"
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_models.py -q` → FAIL (DecisionType 없음/키워드 미지원).

- [ ] **Step 3: 구현** — `simcore/models.py` TradeReason 아래:

```python
class DecisionType(str, Enum):
    BUY = "BUY"
    PARTIAL_SELL = "PARTIAL_SELL"
    FULL_SELL = "FULL_SELL"
    FORCED_SELL = "FORCED_SELL"
```

Trade에 realized_pnl 뒤 추가:

```python
    decision_type: DecisionType = DecisionType.BUY
    trigger_rule: str = ""
```

`simcore/engine.py` PendingBuy·PendingSell 각 dataclass 끝에 추가:

```python
    decision_type: "DecisionType" = None   # 결정 시점 확정
    trigger_rule: str = ""
```

(engine.py 상단 import에 `from simcore.models import ... DecisionType` 추가.)

`simcore/portfolio.py` buy/sell 시그니처에 `decision_type=DecisionType.BUY, trigger_rule=""` (buy) / `decision_type=DecisionType.FULL_SELL, trigger_rule=""` (sell) 추가하고 Trade 생성에 키워드로 전달. (portfolio.py import에 DecisionType 추가.)

- [ ] **Step 4: 통과 확인** — `pytest tests/test_models.py tests/test_portfolio.py -q` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: DecisionType 결정유형+trigger_rule 모델·portfolio 배선"`

---

### Task 2: 엔진이 결정 시점에 유형·트리거 확정

**Files:**
- Modify: `simcore/engine.py` (evaluate_close 매도/매수 분기 :92-125, fill_open _sell 호출 :151-153, _buy :186, check_stops :229-232)
- Test: `tests/test_engine_orders.py`, `tests/test_engine_risk.py`

**Interfaces:**
- Consumes: Task 1의 DecisionType·Pending 필드·portfolio 키워드.
- Produces: 모든 Trade에 정확한 decision_type/trigger_rule. FORCED_SELL trigger ∈ {"R18","R5+R23","R7","R10"}; graded → PARTIAL_SELL/FULL_SELL trigger=적신호 코드 join; BUY trigger=`f"게이트+{green_score}점"`.

- [ ] **Step 1: 실패 테스트** — `tests/test_engine_orders.py`에 추가(픽스처는 기존 `_buy_snap`/`snap` 활용):

```python
def test_forced_sell_r5r23_records_forced_decision():
    from simcore.models import DecisionType
    e = make_engine()
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1","G4","G7"), green_score=18, gate=True)})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    # R5+R23 강제(점수 8이어도) — red_score 낮게
    e.evaluate_close(D2, Market.KR, {"A": snap("A", red=("R5","R23"), red_score=8)})
    e.fill_open(D3, Market.KR, {"A": 95.0}, fx_rate=1300.0)
    t = [x for x in e.states["국내형"].portfolio.trades if x.side.value=="SELL"][-1]
    assert t.decision_type == DecisionType.FORCED_SELL and t.trigger_rule == "R5+R23"

def test_graded_full_and_partial_and_buy_decision():
    from simcore.models import DecisionType
    e = make_engine()
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1","G4","G7"), green_score=19, gate=True)})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    buy = [x for x in e.states["국내형"].portfolio.trades if x.side.value=="BUY"][-1]
    assert buy.decision_type == DecisionType.BUY and "19" in buy.trigger_rule
    e.evaluate_close(D2, Market.KR, {"A": snap("A", red=("R1","R4","R11"), red_score=15)})
    e.fill_open(D3, Market.KR, {"A": 99.0}, fx_rate=1300.0)
    t = [x for x in e.states["국내형"].portfolio.trades if x.side.value=="SELL"][-1]
    assert t.decision_type == DecisionType.FULL_SELL
```

`tests/test_engine_risk.py`에 R7/R10 강제 추가:

```python
def test_stop_and_trailing_record_forced_r7_r10():
    from simcore.models import DecisionType
    # 기존 손절/트레일링 테스트 패턴 재사용 — 청산 후 마지막 SELL 의 trigger 확인
    # STOP_LOSS → "R7", TRAILING_STOP → "R10", 둘 다 FORCED_SELL
    ...  # 기존 픽스처로 손절 유발 후:
    # assert last_sell.decision_type == DecisionType.FORCED_SELL and last_sell.trigger_rule in ("R7","R10")
```

(구현자: test_engine_risk.py 기존 손절·트레일링 테스트를 참고해 마지막 SELL trade의 decision_type/trigger를 단언하도록 구체화.)

- [ ] **Step 2: 실패 확인** — `pytest tests/test_engine_orders.py tests/test_engine_risk.py -q` → FAIL.

- [ ] **Step 3: 구현** — `simcore/engine.py`:
  - evaluate_close 매도 분기(:99-113): `forced` 분기에서 trigger 결정 —
    ```python
    if forced:
        if s.close <= stop_px: trig = "R7"
        elif "R18" in red: trig = "R18"
        else: trig = "R5+R23"
        st.pending_sells.append(PendingSell(sym, market, TradeReason.SIGNAL_SELL, len(red),
            s.red_score, tuple(s.red), partial=False,
            decision_type=DecisionType.FORCED_SELL, trigger_rule=trig))
    elif s.red_score >= r.sell_full_min:
        st.pending_sells.append(PendingSell(..., partial=False,
            decision_type=DecisionType.FULL_SELL, trigger_rule="+".join(s.red)))
    elif s.red_score >= r.sell_partial_min:
        st.pending_sells.append(PendingSell(..., partial=True,
            decision_type=DecisionType.PARTIAL_SELL, trigger_rule="+".join(s.red)))
    ```
    (참고: 종가갭 R7 우선 판정은 stop_px 비교. 트레일링 종가갭도 stop_px에 포함되므로 종가갭 강제는 "R7"로 통일 — 장중 트레일링은 check_stops의 R10.)
  - 매수 후보(:123-125): PendingBuy에 `decision_type=DecisionType.BUY, trigger_rule=f"게이트+{s.green_score}점"`.
  - fill_open `_sell` 호출(:151): `decision_type=ps.decision_type, trigger_rule=ps.trigger_rule` 전달. `_sell`·portfolio.sell로 관통.
  - `_buy`(:186): `pf.buy(..., decision_type=b.decision_type or DecisionType.BUY, trigger_rule=b.trigger_rule)`.
  - check_stops(:229-232): `reason` 결정 시 `dt=DecisionType.FORCED_SELL`, `trig = "R10" if reason==TRAILING_STOP else "R7"`, `_sell(..., decision_type=dt, trigger_rule=trig)`.
  - `_sell` 시그니처에 `decision_type=DecisionType.FULL_SELL, trigger_rule=""` 추가해 portfolio.sell로 전달.

- [ ] **Step 4: 통과 확인** — `pytest tests/test_engine_orders.py tests/test_engine_risk.py -q` → PASS. 전체 `pytest tests/ -q` 회귀 확인(기존 SELL 테스트가 reason 유지하는지).

- [ ] **Step 5: Commit** — `git commit -am "feat: 엔진이 결정 시점에 DecisionType/trigger_rule 확정(강제/등급/매수)"`

---

### Task 3: signal_display — 결정 기반 문구 + 미수집 축 (P0-1 표시 · P0-2 로직)

**Files:**
- Modify: `simcore/signal_display.py` (summarize/detail :35-56)
- Test: `tests/test_signal_display.py`

**Interfaces:**
- Consumes: DecisionType.
- Produces: `summarize(fired, score, side, scores, decision_type=None, trigger_rule="") -> str` (decision 우선). `detail(...)` 불변 + 미수집 코드 상태. `describe_decision(decision_type, trigger_rule, score) -> str` 헬퍼.

- [ ] **Step 1: 실패 테스트** — `tests/test_signal_display.py`에 추가:

```python
def test_summarize_uses_decision_not_score():
    from simcore.signal_display import summarize
    from simcore.models import DecisionType
    from simcore.config import SignalScores
    s = SignalScores()
    # R5+R23 강제, score 8 — 재계산이면 "주의", 결정기반이면 "강제 전량매도"
    out = summarize(("R5","R23"), 8, "SELL", s,
                    decision_type=DecisionType.FORCED_SELL, trigger_rule="R5+R23")
    assert "강제 전량매도" in out and "주의" not in out

def test_summarize_forced_causes():
    from simcore.signal_display import summarize
    from simcore.models import DecisionType
    from simcore.config import SignalScores
    s = SignalScores()
    m = {"R18":"지지선 붕괴", "R7":"잠금 손절선 도달", "R10":"최고가 대비 트레일링선 도달"}
    for trig, phrase in m.items():
        out = summarize((), 0, "SELL", s, decision_type=DecisionType.FORCED_SELL, trigger_rule=trig)
        assert phrase in out and "강제 전량매도" in out
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_signal_display.py -q` → FAIL.

- [ ] **Step 3: 구현** — `simcore/signal_display.py`:

```python
_FORCED_PHRASE = {
    "R5+R23": "급락 복합조건",
    "R18": "지지선 붕괴",
    "R7": "잠금 손절선 도달",
    "R10": "최고가 대비 트레일링선 도달",
}

def summarize(fired, score, side, scores, decision_type=None, trigger_rule=""):
    if decision_type is not None:
        from simcore.models import DecisionType
        if decision_type == DecisionType.FORCED_SELL:
            cause = _FORCED_PHRASE.get(trigger_rule, trigger_rule or "강제 조건")
            return f"{cause} → 강제 전량매도"
        if decision_type == DecisionType.PARTIAL_SELL:
            named = [SIGNAL_NAMES.get(c, c) for c in fired if c in scores.points]
            head = " + ".join(named[:3]) or "적신호"
            return f"{head} → 부분 매도 (적신호 {score}점)"
        if decision_type == DecisionType.FULL_SELL:
            named = [SIGNAL_NAMES.get(c, c) for c in fired if c in scores.points]
            head = " + ".join(named[:3]) or "적신호"
            return f"{head} → 전량 매도 (적신호 {score}점)"
    # BUY 또는 decision 미지정(하위호환) → 기존 로직
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

(P0-2 미수집 축: `detail`은 계산되는 기술적 코드만 반환하므로 현행 유지. "미수집" 표기는 프론트 고지(Task 8)에서 처리 — 백엔드는 스텁 코드를 응답에 넣지 않는 현행이 곧 "미계산".)

- [ ] **Step 4: 통과 확인** — `pytest tests/test_signal_display.py -q` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: signal_display 결정기반 문구(강제/등급 매도, 재계산 제거)"`

---

### Task 4: metrics — 위험조정 지표 (P0-3 계산)

**Files:**
- Modify: `simcore/metrics.py` (파일 끝)
- Test: `tests/test_metrics.py`

**Interfaces:**
- Produces: `risk_metrics(equity: pd.Series, trades: pd.DataFrame|None, flows: pd.Series|None=None, periods_per_year: int=252) -> dict` 반환 키: `cagr, volatility, sharpe, sortino, calmar, profit_factor, avg_win, avg_loss, win_loss_ratio, expectancy, max_consecutive_losses, recovery_days`. 무위험=0.

- [ ] **Step 1: 실패 테스트** — `tests/test_metrics.py`에 추가:

```python
def test_risk_metrics_basic():
    import numpy as np, pandas as pd
    from simcore.metrics import risk_metrics
    idx = pd.date_range("2025-01-01", periods=252, freq="B")
    eq = pd.Series(np.linspace(100, 130, 252), index=idx)   # 우상향
    trades = pd.DataFrame({"side": ["SELL","SELL","SELL"], "realized_pnl": [10.0, -4.0, 6.0]})
    m = risk_metrics(eq, trades)
    assert m["cagr"] > 0 and m["calmar"] > 0
    assert m["profit_factor"] == pytest.approx(16.0/4.0)         # 이익합16/손실합4
    assert m["win_loss_ratio"] == pytest.approx((16/2)/4.0)      # 평균이익8/평균손실4
    assert m["max_consecutive_losses"] == 1
    assert m["expectancy"] == pytest.approx((10-4+6)/3)

def test_risk_metrics_empty_and_all_loss():
    import pandas as pd
    from simcore.metrics import risk_metrics
    eq = pd.Series([100.0, 90.0], index=pd.date_range("2025-01-01", periods=2))
    m = risk_metrics(eq, pd.DataFrame({"side":["SELL"], "realized_pnl":[-5.0]}))
    assert m["profit_factor"] == 0.0 and m["avg_win"] == 0.0     # 이익 없음
    m2 = risk_metrics(eq, None)                                   # 거래정보 없음
    assert m2["profit_factor"] == 0.0 and m2["expectancy"] == 0.0
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_metrics.py -q` → FAIL.

- [ ] **Step 3: 구현** — `simcore/metrics.py` 끝에 `risk_metrics` 추가. 구현 지침:
  - 일간수익률 `ret = equity.pct_change().dropna()`.
  - `cagr = (equity.iloc[-1]/equity.iloc[0]) ** (periods_per_year/len(ret)) - 1` (len(ret)>0, 아니면 0).
  - `volatility = ret.std(ddof=0) * sqrt(periods_per_year)`.
  - `sharpe = (ret.mean()*periods_per_year) / volatility` (vol>0 else 0).
  - `sortino`: 하방편차만(음수 ret) 사용, 분모 0이면 0.
  - `calmar = cagr / abs(max_drawdown(equity))` (mdd≠0 else 0). max_drawdown 기존 함수 재사용.
  - SELL trades의 realized_pnl 리스트로: 이익합/손실합 → `profit_factor=이익합/|손실합|`(손실합 0이면 0), `avg_win/avg_loss`, `win_loss_ratio=avg_win/avg_loss`(avg_loss 0이면 0), `expectancy=mean(pnl)`, `max_consecutive_losses`(pnl<0 최대 연속), 회복기간=최대낙폭 저점 이후 직전 고점 회복까지 일수(미회복이면 마지막까지 일수).
  - trades None/빈 → pnl 관련 0.

- [ ] **Step 4: 통과 확인** — `pytest tests/test_metrics.py -q` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat: metrics 위험조정 지표(CAGR·Sharpe·Sortino·Calmar·PF·기대값·연속손실·회복기간)"`

---

### Task 5: 벤치마크 초과수익 계산

**Files:**
- Modify: `simcore/metrics.py` (benchmark 헬퍼), `simcore/replay.py` (summary에 benchmark_delta)
- Test: `tests/test_metrics.py`, `tests/test_replay_integration.py`

**Interfaces:**
- Consumes: Task 4 metrics, `data.load_index` (지수 Series).
- Produces: `metrics.benchmark_return(index: pd.Series|None, start, end) -> float|None`. `ReplayResult.summary[char]`에 `benchmark_return: float|None`, `benchmark_delta: float|None`(twr − benchmark_return; 지수 없으면 None), `benchmark_name: str`(KOSPI200/S&P500/혼합/None).

- [ ] **Step 1: 실패 테스트** — `tests/test_metrics.py`:

```python
def test_benchmark_return_and_none():
    import pandas as pd
    from simcore.metrics import benchmark_return
    idx = pd.date_range("2025-01-01", periods=10)
    s = pd.Series(range(100,110), index=idx, dtype=float)
    r = benchmark_return(s, idx[0], idx[-1])
    assert r == pytest.approx(109/100 - 1)
    assert benchmark_return(None, idx[0], idx[-1]) is None
```

`tests/test_replay_integration.py`: 지수 번들 리플레이의 summary에 benchmark_delta 존재 + 지수 없으면 None.

- [ ] **Step 2: 실패 확인** — FAIL.

- [ ] **Step 3: 구현** — `metrics.benchmark_return`(asof 시작/끝 종가 비율−1, None 안전). `replay.py` summary 집계 루프(report.py 또는 replay.py where summary built)에서 캐릭터 시장의 지수로 benchmark_return 계산: 단일시장=해당 지수; 범용형=KR/US 지수 단순평균(문서화). delta = twr − benchmark_return(둘 다 있을 때), 아니면 None. summary dict에 3키 추가.

- [ ] **Step 4: 통과 확인** — PASS. 전체 회귀.

- [ ] **Step 5: Commit** — `git commit -am "feat: 벤치마크 초과수익(benchmark_delta) 계산 리플레이 배선"`

---

### Task 6: 영속 — 리플레이/시드 DataFrame + 라이브 DB 컬럼

**Files:**
- Modify: `simcore/report.py`(trades DataFrame에 decision_type/trigger_rule), `simcore/replay.py`(동), `simcore/live/db.py`(TradeRow :100 뒤 2컬럼), `simcore/live/repository.py`(persist/append_new_trades 매핑)
- Test: `tests/test_replay_integration.py`, `tests/live/test_repository.py`, `tests/live/test_equivalence.py`

**Interfaces:**
- Consumes: Task 1·2 Trade 필드.
- Produces: trades DataFrame·DB에 `decision_type`(문자열 value)·`trigger_rule` 컬럼.

- [ ] **Step 1: 실패 테스트** — replay trades DataFrame에 `decision_type`/`trigger_rule` 컬럼 존재 + FORCED 케이스 값 확인; repository 왕복 테스트에 두 컬럼 저장·복원.
- [ ] **Step 2: 실패 확인** — FAIL.
- [ ] **Step 3: 구현** — report.py/replay.py trades 레코드 dict에 `"decision_type": t.decision_type.value, "trigger_rule": t.trigger_rule`. db.py TradeRow에 `decision_type: Mapped[str] = mapped_column(String, default="BUY")`, `trigger_rule: Mapped[str] = mapped_column(String, default="")`. repository append_new_trades/persist가 Trade→TradeRow 매핑에 두 필드 포함, 조회 시 역매핑.
- [ ] **Step 4: 통과 확인** — `pytest tests/ -q` (equivalence 포함) PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat: 결정유형/트리거 영속(리플레이·시드·라이브 DB)"`

---

### Task 7: 대시보드 백엔드 — 결정 노출 + 위험지표 + 벤치마크 경고

**Files:**
- Modify: `dashboard/backend/queries.py`(trades/recent_trades에 decision_type/trigger_rule), `dashboard/backend/app.py`(:174-178 summarize 호출), `dashboard/backend/summary.py`(metrics에 risk_metrics·benchmark_delta·null 경고 플래그)
- Test: `tests/dashboard/test_api.py`, `tests/dashboard/test_queries.py`, `tests/dashboard/test_summary.py`

**Interfaces:**
- Consumes: Task 3 summarize(결정 인자), Task 4 risk_metrics, Task 5 benchmark, Task 6 컬럼.
- Produces: TradeOut에 decision_type/trigger_rule + signal_summary가 결정 기반. Metrics 응답에 risk 지표·benchmark_delta·`benchmark_available: bool`.

- [ ] **Step 1: 실패 테스트** — API 응답 trades[].decision_type 존재 + FORCED_SELL의 signal_summary에 "강제 전량매도"; metrics 응답에 sharpe 등 + benchmark_available. (DB 픽스처 사용.)
- [ ] **Step 2: 실패 확인** — FAIL.
- [ ] **Step 3: 구현** — queries가 두 컬럼 로드. app.character_trades(:174-178): `sd.summarize(t["fired"], score, t["side"], _SCORES, decision_type=DecisionType(t["decision_type"]), trigger_rule=t["trigger_rule"])`. summary.detail_metrics/card_summary에 risk_metrics·benchmark_delta 추가, benchmark None이면 `benchmark_available=False`(숨김 아님). TradeOut 스키마 필드 추가.
- [ ] **Step 4: 통과 확인** — `pytest tests/dashboard/ -q` PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat: 대시보드 API 결정유형·위험지표·벤치마크 경고 노출"`

---

### Task 8: 프론트 — 기술적 신호 라벨·결정 표시·모드/as-of·벤치마크 우선

**Files:**
- Modify: `dashboard/frontend/src/types.ts`, 신호 배지·범례·상세 컴포넌트, 거래내역 테이블, 성과/지표 컴포넌트, 앱 셸(모드·as-of 배지)
- Test: `dashboard/frontend/src/**/*.test.ts(x)` (vitest)

**Interfaces:**
- Consumes: Task 7 API(decision_type/trigger_rule/risk 지표/benchmark_available).

- [ ] **Step 1: 실패 테스트(vitest)** — 신호 라벨이 "기술적 매수/매도 신호"인지; FORCED_SELL 행이 "강제 전량매도" 문구; benchmark_available=false면 "벤치마크 미수집" 경고 렌더; 모드 배지("PAPER")·데이터 as-of 표시 존재; "뉴스·공시·수급 미반영" 고지 렌더.
- [ ] **Step 2: 실패 확인** — `npx vitest run` FAIL.
- [ ] **Step 3: 구현** —
  - types.ts에 `decision_type`,`trigger_rule`, risk 지표, `benchmark_available` 추가.
  - 신호 배지/범례/상세 헤더 문구 "청/적신호"→"**기술적 매수/매도 신호**"; 판단/카드에 "뉴스·공시·수급은 현재 판단에 반영되지 않음" 고지; 미계산 외부 축은 "미수집/판단 불가" 배지.
  - 거래내역: signal_summary(결정 기반) 그대로 렌더 + decision_type 칩(부분/전량/강제 색 구분). red_score 재계산 문구 사용 금지.
  - 성과: **전략 vs 벤치마크 초과수익을 1순위**로, benchmark_available=false면 경고 배지. 위험조정 지표 스트립(Sharpe/Sortino/Calmar/PF/기대값/최대연속손실/회복기간), 각 값에 표본기간·거래수·비용·데이터버전 꼬리표(툴팁). "검증됨" 라벨 없음. MDD "최대 낙폭 X%" 문구.
  - 앱 셸 상단: 운영 모드 배지(PAPER) + 각 시장 데이터 as-of·지연 표시(WebSocket 연결과 구분).
- [ ] **Step 4: 통과 확인** — `cd dashboard/frontend && npm run build && npx vitest run` PASS.
- [ ] **Step 5: Commit** — `git commit -am "feat: 프론트 기술적신호 라벨·결정기반 표시·PAPER모드·벤치마크 우선"`

---

### Task 9: 문서·재시딩·릴리즈 배선

**Files:**
- Modify: `docs/trading-rules.md`(결정 유형·표시 규칙·위험지표 정의 절), `README.md`
- Test: 전체 스위트 + 프론트 빌드 + 재시딩 스모크

- [ ] **Step 1: 문서** — trading-rules.md에 DecisionType/trigger_rule·표시 매핑·위험지표 정의(무위험0·범용형 혼합벤치마크) 절 추가. README 갱신. config↔문서 정합.
- [ ] **Step 2: 전체 테스트** — `pytest tests/ -q` + `cd dashboard/frontend && npm run build && npx vitest run` 모두 PASS 확인.
- [ ] **Step 3: 재시딩** — `DATABASE_URL=<라이브 DB> python -m dashboard.scripts.seed_from_replay --force` (신규 컬럼·벤치마크·지표 반영). 대시보드 스모크: FORCED_SELL 거래가 "강제 전량매도"로 표시, benchmark·위험지표·PAPER 배지 확인.
- [ ] **Step 4: Commit** — `git commit -am "docs: 결정유형·위험지표 규칙 문서 + 재시딩"`

---

## 완료 후 (플랜 밖)

ALL 9 TASKS COMPLETE → `.superpowers/sdd/progress.md` 갱신 → 최종 전체브랜치 리뷰(opus) → dev 병합 + 브랜치 삭제 → dev→main 승격 → **v1.8.0** 태그 + CHANGELOG/패치노트 (CLAUDE.md). 리포트 P0 완료 조건 재검증은 Codex 재감사가 수행.
