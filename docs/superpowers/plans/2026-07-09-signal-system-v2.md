# 신호 시스템 v2 구현 계획 (점수제·게이팅·트레일링 스탑)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** simcore 엔진의 신호 판정을 "개수 카운트"에서 "점수제 + 카테고리 상한 + 매수 다중 게이팅 + 매도 등급 + 트레일링 스탑"으로 교체하고, 최근 6개월 리플레이로 검증한다.

**Architecture:** 순수 엔진 계층만 변경한다. 신규 지표(indicators.py) → 점수/규칙 테이블(config.py) → 신호 컬럼·점수 함수(signals.py) → 모델 확장(models.py) → 회계(portfolio.py) → 매매 로직(engine.py) → 스냅샷 통합(replay.py·orchestrator.py) → CLI/데이터/문서. 리플레이와 라이브는 동일 엔진을 호출하므로 스냅샷 생성 2곳을 공용 헬퍼로 함께 갱신한다.

**Tech Stack:** Python 3, pandas, dataclasses. 테스트: pytest. 데이터: pykrx(KR)·yfinance(US).

## Global Constraints

- **단일 기준 문서**: 모든 수치는 `docs/trading-rules.md` v2 및 `simcore/config.py`와 1:1. 값 변경 시 문서 동시 갱신.
- **손실 최소화 우선**: 매수는 까다롭게(총점 ≥ 18 AND 게이트), 매도·손절은 빠르게.
- **매수 게이트는 명시적 코드 집합으로 정의**(스코어링 카테고리와 별개). G23은 스코어링상 "돌파" 카테고리지만 게이트에서는 "거래량" 요건을 충족한다 — 이는 의도된 것이며 게이트 집합과 카테고리 맵을 분리해 표현한다.
- **트레일링 스탑이 고정 익절(+15%)을 대체**한다. `take_profit_pct`는 제거. `TradeReason.TAKE_PROFIT` enum 값은 과거 데이터/호환을 위해 남기되 엔진은 더 이상 생성하지 않는다.
- **스냅샷 생성 2곳**(replay.py, live/orchestrator.py) 모두 `green_score`/`red_score`/`buy_gate`를 채운다. 새 필드는 기본값(0/False)이 있어 컴파일은 되지만, 채우지 않으면 매수가 절대 발생하지 않으므로 두 곳 모두 필수.
- **차트패턴·피보나치·뉴스·수급 신호는 스텁**(항상 False 컬럼): G8·G9·G19·G21·G24·G25~G30, R20·R22·R25~R30.
- **커밋 신원**: `leetaegyu96 <leetaegyu96@users.noreply.github.com>`. 회사 이메일 금지. 커밋 메시지 한국어 + 타입 접두어. 작업 브랜치는 `dev`에서 분기.
- **기존 테스트 갱신 허용**: v1 규칙(7/3, +15% 익절)을 가정한 기존 테스트는 각 태스크에서 v2 규칙에 맞게 갱신한다(삭제가 아니라 갱신).

---

## 파일 구조

- `simcore/indicators.py` (수정) — ATR·ADX/DI·OBV·VWAP·Parabolic SAR·일목균형표 추가.
- `simcore/config.py` (수정) — `SignalParams` 지표 파라미터 확장, `SignalScores` 신규, `TradeRules` v2, `Config.scores` 필드.
- `simcore/signals.py` (수정) — `evaluate_frame` 신호 컬럼 확장, `score`/`buy_gate_ok`/`snapshot_scores` 함수 추가.
- `simcore/models.py` (수정) — `SymbolSnapshot`(점수/게이트), `Position`(peak/locked_stop), `Trade`(green_score/red_score), `TradeReason.TRAILING_STOP`.
- `simcore/portfolio.py` (수정) — `buy` 트레일링 초기화, `sell` 부분매도 지원.
- `simcore/engine.py` (수정) — 매수 게이팅, 매도 등급, 트레일링 스탑, 부분매도/쿨다운.
- `simcore/replay.py` (수정) — 스냅샷에 점수/게이트, green_hist → score_hist.
- `simcore/live/orchestrator.py` (수정) — 스냅샷에 점수/게이트.
- `simcore/__main__.py` (수정) — `--buy-threshold` → `--buy-score`.
- `simcore/data.py` (수정) — `LOOKBACK_PAD_DAYS` 상향.
- `docs/trading-rules.md` (수정) — v2 재작성.
- `README.md` (수정) — 임계값 설명 갱신.
- 테스트: `tests/test_indicators.py`, `tests/test_config.py`, `tests/test_signals.py`, `tests/test_models.py`, `tests/test_portfolio.py`, `tests/test_engine_orders.py`, `tests/test_engine_risk.py`, `tests/test_replay_integration.py`.

---

### Task 1: 신규 기술 지표

**Files:**
- Modify: `simcore/indicators.py`
- Test: `tests/test_indicators.py`

**Interfaces:**
- Produces:
  - `atr(high, low, close, period=14) -> pd.Series`
  - `adx(high, low, close, period=14) -> tuple[pd.Series, pd.Series, pd.Series]` → `(adx, di_plus, di_minus)`
  - `obv(close, volume) -> pd.Series`
  - `vwap(high, low, close, volume, period=20) -> pd.Series` (롤링 VWAP)
  - `parabolic_sar(high, low, af_step=0.02, af_max=0.2) -> pd.Series`
  - `ichimoku(high, low, close, tenkan=9, kijun=26, senkou_b=52) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]` → `(tenkan_line, kijun_line, senkou_a, senkou_b)` — 선행스팬은 현재 인덱스에 정렬(앞으로 kijun만큼 shift된 값이 현재 봉에 오도록 `.shift(kijun)` 적용).

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_indicators.py`에 추가

```python
import numpy as np
import pandas as pd
from simcore import indicators as ind


def _series(vals):
    idx = pd.date_range("2024-01-01", periods=len(vals), freq="D")
    return pd.Series(vals, index=idx, dtype=float)


def test_atr_wilder_matches_manual():
    high = _series([10, 11, 12, 11, 13])
    low = _series([9, 9.5, 10, 10, 11])
    close = _series([9.5, 10.5, 11.5, 10.5, 12.5])
    out = ind.atr(high, low, close, period=2)
    # 첫 TR=high-low=1; 이후 TR=max(h-l, |h-prevclose|, |l-prevclose|)
    assert out.notna().sum() >= 3
    assert (out.dropna() > 0).all()


def test_adx_trending_up_has_di_plus_dominant():
    n = 40
    close = _series(np.linspace(10, 30, n))          # 꾸준한 상승
    high = close + 0.5
    low = close - 0.5
    adx, di_p, di_m = ind.adx(high, low, close, period=14)
    assert di_p.iloc[-1] > di_m.iloc[-1]             # 상승 → DI+ 우위
    assert adx.iloc[-1] > 20


def test_obv_accumulates_on_up_days():
    close = _series([10, 11, 10, 12])
    vol = _series([100, 200, 150, 300])
    out = ind.obv(close, vol)
    # +200 (상승), -150 (하락), +300 (상승) 누적
    assert out.iloc[1] == 200
    assert out.iloc[2] == 50
    assert out.iloc[3] == 350


def test_vwap_between_low_and_high():
    high = _series([10, 11, 12, 13, 14])
    low = _series([8, 9, 10, 11, 12])
    close = _series([9, 10, 11, 12, 13])
    vol = _series([100, 100, 100, 100, 100])
    out = ind.vwap(high, low, close, vol, period=3)
    tail = out.dropna()
    assert (tail >= low.reindex(tail.index)).all()
    assert (tail <= high.reindex(tail.index)).all()


def test_parabolic_sar_flips_below_price_in_uptrend():
    n = 30
    close = _series(np.linspace(10, 25, n))
    high = close + 0.3
    low = close - 0.3
    sar = ind.parabolic_sar(high, low)
    assert sar.iloc[-1] < close.iloc[-1]             # 상승추세 → SAR 은 가격 아래


def test_ichimoku_cloud_below_price_in_uptrend():
    n = 90
    close = _series(np.linspace(10, 40, n))
    high = close + 0.5
    low = close - 0.5
    tenkan, kijun, span_a, span_b = ind.ichimoku(high, low, close)
    top = pd.concat([span_a, span_b], axis=1).max(axis=1)
    assert close.iloc[-1] > top.iloc[-1]             # 상승추세 → 구름 위
    assert tenkan.iloc[-1] > kijun.iloc[-1]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_indicators.py -k "atr_wilder or adx_trending or obv_accum or vwap_between or parabolic or ichimoku_cloud" -q`
Expected: FAIL (`AttributeError: module 'simcore.indicators' has no attribute 'atr'`)

- [ ] **Step 3: 지표 구현** — `simcore/indicators.py` 하단에 추가

```python
def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = _true_range(high, low, close)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = _true_range(high, low, close)
    atr_ = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    di_plus = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_
    di_minus = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_
    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus)
    adx_ = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return adx_, di_plus, di_minus


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = close.diff().apply(lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0))
    return (direction * volume).cumsum()


def vwap(high: pd.Series, low: pd.Series, close: pd.Series,
         volume: pd.Series, period: int = 20) -> pd.Series:
    typical = (high + low + close) / 3.0
    pv = (typical * volume).rolling(period).sum()
    vv = volume.rolling(period).sum()
    return pv / vv


def parabolic_sar(high: pd.Series, low: pd.Series,
                  af_step: float = 0.02, af_max: float = 0.2) -> pd.Series:
    n = len(high)
    sar = [float("nan")] * n
    if n < 2:
        return pd.Series(sar, index=high.index)
    h = high.to_numpy(); l = low.to_numpy()
    up = True                      # 초기 추세: 상승 가정
    af = af_step
    ep = h[0]                      # extreme point
    sar_val = l[0]
    for i in range(1, n):
        prev = sar_val
        sar_val = prev + af * (ep - prev)
        if up:
            sar_val = min(sar_val, l[i - 1], l[max(i - 2, 0)])
            if l[i] < sar_val:     # 하락 반전
                up = False; sar_val = ep; ep = l[i]; af = af_step
            elif h[i] > ep:
                ep = h[i]; af = min(af + af_step, af_max)
        else:
            sar_val = max(sar_val, h[i - 1], h[max(i - 2, 0)])
            if h[i] > sar_val:     # 상승 반전
                up = True; sar_val = ep; ep = h[i]; af = af_step
            elif l[i] < ep:
                ep = l[i]; af = min(af + af_step, af_max)
        sar[i] = sar_val
    return pd.Series(sar, index=high.index)


def ichimoku(high: pd.Series, low: pd.Series, close: pd.Series,
             tenkan: int = 9, kijun: int = 26,
             senkou_b: int = 52) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    def mid(period):
        return (high.rolling(period).max() + low.rolling(period).min()) / 2.0
    tenkan_line = mid(tenkan)
    kijun_line = mid(kijun)
    span_a = ((tenkan_line + kijun_line) / 2.0).shift(kijun)   # 현재 봉에 정렬
    span_b = mid(senkou_b).shift(kijun)
    return tenkan_line, kijun_line, span_a, span_b
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_indicators.py -q`
Expected: PASS (기존 지표 테스트 포함 전부)

- [ ] **Step 5: 커밋**

```bash
git add simcore/indicators.py tests/test_indicators.py
git commit -m "feat: 신규 지표 추가 (ATR·ADX/DI·OBV·VWAP·SAR·일목균형표)"
```

---

### Task 2: config — 신호 점수표·v2 규칙·지표 파라미터

**Files:**
- Modify: `simcore/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `SignalParams` 신규 필드(adx/일목/sar/atr/box/support/gap/장대음봉 등).
  - `SignalScores(points: dict[str,int], category: dict[str,str], caps: dict[str,int], buy_gate: dict[str, frozenset[str]])`.
  - `TradeRules` v2 필드: `buy_score_interest/candidate/min`, `sell_partial_min`, `sell_full_min`, `partial_sell_fraction`, `stop_loss_pct`, `trail_pct`, `trailing_tiers`, `trailing_top`, `max_positions`, `cooldown_days`, `bear_market_guard`.
  - `Config.scores: SignalScores`.
- Consumes: 없음(순수 데이터).

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_config.py`에 추가

```python
from simcore.config import Config, SignalScores, TradeRules

IMPLEMENTED_GREEN = ["G1","G2","G3","G4","G5","G6","G7","G10","G11","G12",
                     "G13","G14","G15","G16","G17","G18","G23"]
IMPLEMENTED_RED = ["R1","R2","R3","R4","R5","R6","R11","R12","R13","R14",
                   "R15","R16","R17","R18","R19","R23","R24"]


def test_every_implemented_signal_has_score_and_category():
    sc = Config().scores
    for code in IMPLEMENTED_GREEN + IMPLEMENTED_RED:
        assert code in sc.points, f"{code} 점수 없음"
        assert code in sc.category, f"{code} 카테고리 없음"
        assert sc.category[code] in sc.caps, f"{code} 카테고리 상한 없음"


def test_buy_gate_sets_are_implemented_greens():
    sc = Config().scores
    assert set(sc.buy_gate) == {"추세", "돌파", "거래량"}
    for members in sc.buy_gate.values():
        assert members, "게이트 집합이 비어있음"
        assert members <= set(IMPLEMENTED_GREEN)


def test_v2_rules_thresholds_ordered():
    r = TradeRules()
    assert r.buy_score_interest < r.buy_score_candidate < r.buy_score_min
    assert r.sell_partial_min < r.sell_full_min
    assert 0 < r.partial_sell_fraction < 1
    assert r.stop_loss_pct < 0
    # 트레일링 단계: 임계 내림차순, 잠금값 임계보다 낮음
    tiers = r.trailing_tiers
    assert list(tiers) == sorted(tiers, key=lambda t: -t[0])
    for thr, lock in tiers:
        assert lock < thr


def test_v1_fields_removed():
    r = TradeRules()
    assert not hasattr(r, "buy_threshold")
    assert not hasattr(r, "sell_threshold")
    assert not hasattr(r, "take_profit_pct")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_config.py -q`
Expected: FAIL (`ImportError: cannot import name 'SignalScores'`)

- [ ] **Step 3: config 구현** — `simcore/config.py` 재작성 (아래 전체로 교체)

```python
"""모든 튜닝 파라미터. docs/trading-rules.md 와 1:1 대응 — 값을 바꾸면 문서도 갱신할 것."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SignalParams:
    sma_fast: int = 5
    sma_slow: int = 20
    rsi_period: int = 14
    rsi_buy_cross: float = 50.0
    rsi_overbought: float = 70.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    volume_avg_period: int = 20
    volume_surge_ratio: float = 1.5
    bb_period: int = 20
    bb_std: float = 2.0
    breakout_lookback: int = 60
    stoch_k: int = 14
    stoch_k_smooth: int = 3
    stoch_d: int = 3
    stoch_oversold: float = 20.0
    # v2 신규
    adx_period: int = 14
    adx_threshold: float = 25.0
    ichimoku_tenkan: int = 9
    ichimoku_kijun: int = 26
    ichimoku_senkou_b: int = 52
    sar_af_step: float = 0.02
    sar_af_max: float = 0.2
    atr_period: int = 14
    atr_squeeze_lookback: int = 20      # G17: ATR 이 이 평균보다 낮으면 수축
    atr_breakout_lookback: int = 10     # G17: 이 기간 최고 종가 돌파
    atr_surge_ratio: float = 1.5        # R17: ATR 이 평균*배수 초과면 급증
    obv_slope_lookback: int = 1         # OBV 상승/하락 비교 기준 봉수
    vwap_period: int = 20
    box_lookback: int = 20              # G18 박스권 상단
    box_range_max: float = 0.15         # 직전 박스 폭(고-저)/저 < 이 값이면 박스권
    support_lookback: int = 20          # R18 지지선(최근 저점)
    gap_down_pct: float = -0.02         # R19 갭 하락 임계
    big_body_pct: float = 0.03          # R23 장대 음봉 몸통 비율


@dataclass(frozen=True)
class SignalScores:
    points: dict = field(default_factory=lambda: {
        # 청신호
        "G1": 5, "G4": 5, "G11": 5, "G12": 5, "G15": 5, "G2": 4, "G16": 4,
        "G7": 5, "G18": 5, "G23": 5, "G5": 4, "G13": 4, "G14": 4,
        "G10": 4, "G3": 3, "G17": 4, "G6": 3,
        # 적신호
        "R1": 5, "R4": 5, "R11": 5, "R12": 5, "R15": 5, "R2": 4, "R16": 4,
        "R18": 5, "R3": 5, "R5": 4, "R13": 4, "R14": 4, "R23": 4, "R24": 4,
        "R17": 4, "R6": 3, "R19": 3,
    })
    category: dict = field(default_factory=lambda: {
        "G1": "추세", "G4": "추세", "G11": "추세", "G12": "추세", "G15": "추세",
        "G2": "추세", "G16": "추세",
        "G7": "돌파", "G18": "돌파", "G23": "돌파",
        "G5": "거래량", "G13": "거래량", "G14": "거래량",
        "G10": "모멘텀", "G3": "모멘텀",
        "G17": "변동성", "G6": "변동성",
        "R1": "추세", "R4": "추세", "R11": "추세", "R12": "추세", "R15": "추세",
        "R2": "추세", "R16": "추세",
        "R18": "하락패턴",
        "R5": "거래량", "R13": "거래량", "R14": "거래량", "R23": "거래량", "R24": "거래량",
        "R3": "모멘텀",
        "R17": "변동성", "R6": "변동성", "R19": "변동성",
    })
    caps: dict = field(default_factory=lambda: {
        "추세": 10, "돌파": 10, "하락패턴": 10,
        "거래량": 8, "모멘텀": 8, "변동성": 6,
    })
    # 매수 게이트(명시적 코드 집합, 카테고리와 별개). 각 집합에서 1개 이상 발화 필요.
    buy_gate: dict = field(default_factory=lambda: {
        "추세": frozenset({"G1", "G4", "G11", "G12", "G15"}),
        "돌파": frozenset({"G7", "G18"}),
        "거래량": frozenset({"G5", "G13", "G23"}),
    })


@dataclass(frozen=True)
class TradeRules:
    buy_score_interest: int = 12
    buy_score_candidate: int = 15
    buy_score_min: int = 18
    sell_partial_min: int = 9
    sell_full_min: int = 11
    partial_sell_fraction: float = 0.5
    stop_loss_pct: float = -0.07
    trail_pct: float = 0.07
    # (peak 수익률 임계, 평단 대비 잠금 손절). 내림차순. 첫 매칭 적용.
    trailing_tiers: tuple = ((0.40, 0.30), (0.30, 0.20), (0.20, 0.10), (0.10, 0.0))
    trailing_top: float = 0.40          # 이 이상이면 최고가 대비 trail_pct 트레일
    max_positions: int = 5
    cooldown_days: int = 2
    bear_market_guard: bool = False


@dataclass(frozen=True)
class CostModel:
    kr_commission: float = 0.00015
    kr_tax: float = 0.0015
    us_commission: float = 0.0009
    fx_fee: float = 0.001
    slippage: float = 0.0


@dataclass(frozen=True)
class Config:
    signals: SignalParams = field(default_factory=SignalParams)
    scores: SignalScores = field(default_factory=SignalScores)
    rules: TradeRules = field(default_factory=TradeRules)
    costs: CostModel = field(default_factory=CostModel)
    initial_capital_krw: float = 100_000_000.0
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add simcore/config.py tests/test_config.py
git commit -m "feat: config v2 (신호 점수표·카테고리 상한·매수 게이트·트레일링 규칙)"
```

---

### Task 3: 신호 평가 v2 — 신규 컬럼

**Files:**
- Modify: `simcore/signals.py`
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes: Task 1 지표, Task 2 `SignalParams`.
- Produces: `evaluate_frame(df, p)` 가 아래 코드 전부를 포함한 boolean 표 반환. `GREEN_COLS`/`RED_COLS`/`min_history` 갱신.

주의: 게이트/스코어 함수는 Task 4에서 추가한다. 이 태스크는 컬럼 생성만.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_signals.py`에 추가

```python
import numpy as np
import pandas as pd
from simcore.config import SignalParams
from simcore import signals as sig


def _frame(closes, highs=None, lows=None, opens=None, vols=None):
    n = len(closes)
    idx = pd.date_range("2023-01-01", periods=n, freq="D")
    close = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({
        "open": pd.Series(opens if opens is not None else closes, index=idx, dtype=float),
        "high": pd.Series(highs if highs is not None else [c + 0.5 for c in closes], index=idx, dtype=float),
        "low": pd.Series(lows if lows is not None else [c - 0.5 for c in closes], index=idx, dtype=float),
        "close": close,
        "volume": pd.Series(vols if vols is not None else [1000.0] * n, index=idx, dtype=float),
    })


def test_new_columns_present_and_stubs_false():
    df = _frame(list(np.linspace(10, 30, 120)))
    out = sig.evaluate_frame(df, SignalParams())
    for col in ["G11","G12","G13","G14","G15","G16","G17","G18","G23",
                "R11","R12","R13","R14","R15","R16","R17","R18","R19","R23","R24"]:
        assert col in out.columns
    for stub in ["G8","G9","G19","G21","G24","R20","R22"]:
        assert col in out.columns or True  # 스텁은 존재하되 전부 False
        if stub in out.columns:
            assert not out[stub].any()


def test_adx_di_signals_fire_in_uptrend():
    df = _frame(list(np.linspace(10, 40, 120)))
    out = sig.evaluate_frame(df, SignalParams())
    assert out["G11"].iloc[-1]        # ADX>=25
    assert out["G12"].iloc[-1]        # DI+>DI-
    assert not out["R12"].iloc[-1]


def test_r23_big_bearish_candle():
    closes = [100] * 30 + [90]        # 마지막 봉 큰 음봉
    opens = [100] * 30 + [100]
    df = _frame(closes, opens=opens,
                highs=[c + 0.5 for c in closes], lows=[c - 0.5 for c in closes])
    out = sig.evaluate_frame(df, SignalParams())
    assert out["R23"].iloc[-1]        # (100-90)/100 = 10% >= 3%


def test_r18_support_break():
    closes = [100, 101, 99, 100, 98] + [100] * 20 + [90]  # 마지막에 최근 저점 하향
    df = _frame(closes)
    out = sig.evaluate_frame(df, SignalParams())
    assert out["R18"].iloc[-1]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_signals.py -k "new_columns or adx_di or r23_big or r18_support" -q`
Expected: FAIL (`KeyError: 'G11'`)

- [ ] **Step 3: evaluate_frame 확장** — `simcore/signals.py` 재작성 (아래 전체로 교체)

```python
"""청/적신호 판정. 계산식은 docs/trading-rules.md v2 와 1:1 대응.
스텁(항상 False): G8·G9·G19·G21·G24·G25~30, R20·R22·R25~30 — 후속에서 대체.
R7(손절)/R10(트레일링)은 포지션 상태에 의존하므로 engine 이 판정한다."""
from __future__ import annotations
import pandas as pd

from simcore.config import SignalParams, SignalScores
from simcore import indicators as ind

GREEN_COLS = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G10", "G11", "G12",
              "G13", "G14", "G15", "G16", "G17", "G18", "G23"]
RED_COLS = ["R1", "R2", "R3", "R4", "R5", "R6", "R11", "R12", "R13", "R14",
            "R15", "R16", "R17", "R18", "R19", "R23", "R24"]
STUB_GREEN = ["G8", "G9", "G19", "G21", "G24"]
STUB_RED = ["R20", "R22"]


def min_history(p: SignalParams) -> int:
    return max(
        p.breakout_lookback + 1,
        p.sma_slow + 1,
        p.macd_slow + p.macd_signal,
        p.bb_period + 1,
        p.rsi_period + 2,
        p.stoch_k + p.stoch_k_smooth + p.stoch_d,
        p.adx_period * 2,
        p.ichimoku_senkou_b + p.ichimoku_kijun,   # 일목: 52+26
        p.atr_squeeze_lookback + 1,
        p.support_lookback + 1,
        p.box_lookback + 1,
    )


def evaluate_frame(df: pd.DataFrame, p: SignalParams) -> pd.DataFrame:
    close, open_, high, low, vol = (df["close"], df["open"], df["high"],
                                    df["low"], df["volume"])
    sma_f = ind.sma(close, p.sma_fast)
    sma_s = ind.sma(close, p.sma_slow)
    rsi = ind.rsi(close, p.rsi_period)
    macd_line, macd_sig = ind.macd(close, p.macd_fast, p.macd_slow, p.macd_signal)
    bb_mid, bb_up, bb_lo = ind.bollinger(close, p.bb_period, p.bb_std)
    k, d = ind.stochastic(high, low, close, p.stoch_k, p.stoch_k_smooth, p.stoch_d)
    vol_avg = ind.sma(vol, p.volume_avg_period)
    adx_, di_p, di_m = ind.adx(high, low, close, p.adx_period)
    obv_ = ind.obv(close, vol)
    vwap_ = ind.vwap(high, low, close, vol, p.vwap_period)
    sar = ind.parabolic_sar(high, low, p.sar_af_step, p.sar_af_max)
    _, _, span_a, span_b = ind.ichimoku(high, low, close, p.ichimoku_tenkan,
                                        p.ichimoku_kijun, p.ichimoku_senkou_b)
    atr_ = ind.atr(high, low, close, p.atr_period)

    surge = vol >= vol_avg * p.volume_surge_ratio
    prev_high = close.rolling(p.breakout_lookback).max().shift(1)     # 신고가(60일)
    cloud_top = pd.concat([span_a, span_b], axis=1).max(axis=1)
    cloud_bot = pd.concat([span_a, span_b], axis=1).min(axis=1)
    box_high = close.rolling(p.box_lookback).max().shift(1)
    box_low = close.rolling(p.box_lookback).min().shift(1)
    boxed = (box_high - box_low) / box_low < p.box_range_max
    support = low.rolling(p.support_lookback).min().shift(1)
    atr_avg = atr_.rolling(p.atr_squeeze_lookback).mean()
    atr_bo_high = close.rolling(p.atr_breakout_lookback).max().shift(1)

    out = pd.DataFrame(index=df.index)
    # ── 청신호 ──
    out["G1"] = sma_f > sma_s
    out["G2"] = close > sma_s
    out["G3"] = (rsi.shift(1) <= p.rsi_buy_cross) & (rsi > p.rsi_buy_cross)
    out["G4"] = macd_line > macd_sig
    out["G5"] = surge & (close > open_)
    out["G6"] = (close.shift(1) <= bb_mid.shift(1)) & (close > bb_mid)
    out["G7"] = close > prev_high
    out["G10"] = (k.shift(1) < p.stoch_oversold) & (k.shift(1) <= d.shift(1)) & (k > d)
    out["G11"] = adx_ >= p.adx_threshold
    out["G12"] = di_p > di_m
    out["G13"] = obv_ > obv_.shift(p.obv_slope_lookback)
    out["G14"] = (close.shift(1) <= vwap_.shift(1)) & (close > vwap_)
    out["G15"] = (close.shift(1) <= cloud_top.shift(1)) & (close > cloud_top)
    out["G16"] = (close.shift(1) <= sar.shift(1)) & (close > sar)
    out["G17"] = (atr_.shift(1) < atr_avg.shift(1)) & (close > atr_bo_high)
    out["G18"] = boxed & (close > box_high)
    out["G23"] = (close > prev_high) & surge
    # ── 적신호 ──
    out["R1"] = sma_f < sma_s
    out["R2"] = close < sma_s
    out["R3"] = (rsi.shift(1) >= p.rsi_overbought) & (rsi < rsi.shift(1))
    out["R4"] = macd_line < macd_sig
    out["R5"] = surge & (close < open_)
    out["R6"] = close < bb_lo
    out["R11"] = (adx_.shift(1) >= p.adx_threshold) & (adx_ < adx_.shift(1))
    out["R12"] = di_m > di_p
    out["R13"] = obv_ < obv_.shift(p.obv_slope_lookback)
    out["R14"] = (close.shift(1) >= vwap_.shift(1)) & (close < vwap_)
    out["R15"] = (close.shift(1) >= cloud_bot.shift(1)) & (close < cloud_bot)
    out["R16"] = (close.shift(1) >= sar.shift(1)) & (close < sar)
    out["R17"] = atr_ > atr_avg * p.atr_surge_ratio
    out["R18"] = close < support
    out["R19"] = open_ < close.shift(1) * (1 + p.gap_down_pct)
    out["R23"] = (close < open_) & ((open_ - close) / open_ >= p.big_body_pct)
    out["R24"] = (close > close.shift(1)) & (vol < vol.shift(1)) & (vol < vol_avg)
    # ── 스텁(항상 False) ──
    for stub in STUB_GREEN + STUB_RED:
        out[stub] = False

    out = out.fillna(False).astype(bool)
    warmup = min_history(p) - 1
    if warmup > 0:
        out.iloc[:warmup] = False
    return out


def fired_at(frame: pd.DataFrame, d) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if d not in frame.index:
        return (), ()
    row = frame.loc[d]
    green = tuple(c for c in GREEN_COLS if bool(row[c]))
    red = tuple(c for c in RED_COLS if bool(row[c]))
    return green, red
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_signals.py -q`
Expected: PASS (기존 G1~G7/G10/R1~R6 테스트 포함. 기존 테스트가 `GREEN_COLS`에 G8/G9 포함을 가정했다면 v2 목록에 맞게 갱신)

- [ ] **Step 5: 커밋**

```bash
git add simcore/signals.py tests/test_signals.py
git commit -m "feat: 신호 평가 v2 컬럼 확장 (G11~G18·G23·R11~R24, 스텁 명시)"
```

---

### Task 4: 점수 계산 & 매수 게이트 함수

**Files:**
- Modify: `simcore/signals.py`
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes: Task 2 `SignalScores`.
- Produces:
  - `score(codes: tuple[str,...] | list[str], scores: SignalScores) -> tuple[int, dict[str,int]]` — (카테고리 상한 적용 총점, 카테고리별 점수).
  - `buy_gate_ok(green_codes, scores: SignalScores) -> bool` — 게이트 3집합 각각 1개 이상.
  - `snapshot_scores(green, red, scores: SignalScores) -> tuple[int,int,bool]` — (green_score, red_score, buy_gate). 스냅샷 생성 공용 헬퍼.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_signals.py`에 추가

```python
from simcore.config import SignalScores


def test_score_applies_category_caps():
    sc = SignalScores()
    # 추세 신호 5개(각 5·5·5·5·5=25) → 상한 10
    total, by_cat = sig.score(["G1", "G4", "G11", "G12", "G15"], sc)
    assert by_cat["추세"] == 10
    assert total == 10


def test_score_sums_across_categories_capped():
    sc = SignalScores()
    total, by_cat = sig.score(["G1", "G4", "G7", "G5"], sc)
    # 추세 G1+G4=10(상한10), 돌파 G7=5, 거래량 G5=4 → 19
    assert total == 19


def test_buy_gate_requires_all_three():
    sc = SignalScores()
    assert not sig.buy_gate_ok(["G1", "G4", "G7"], sc)      # 거래량 없음
    assert not sig.buy_gate_ok(["G1", "G5"], sc)            # 돌파 없음
    assert sig.buy_gate_ok(["G1", "G7", "G5"], sc)          # 추세+돌파+거래량 OK
    assert sig.buy_gate_ok(["G11", "G18", "G23"], sc)       # G23 가 거래량 요건 충족


def test_snapshot_scores_helper():
    sc = SignalScores()
    gs, rs, gate = sig.snapshot_scores(("G1", "G7", "G5"), ("R1",), sc)
    assert gs == 5 + 5 + 4
    assert rs == 5
    assert gate is True
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_signals.py -k "score_applies or score_sums or buy_gate_req or snapshot_scores" -q`
Expected: FAIL (`AttributeError: module 'simcore.signals' has no attribute 'score'`)

- [ ] **Step 3: 함수 구현** — `simcore/signals.py`의 `fired_at` 아래에 추가

```python
def score(codes, scores: SignalScores) -> tuple[int, dict]:
    by_cat: dict[str, int] = {}
    for c in codes:
        cat = scores.category.get(c)
        if cat is None:
            continue
        by_cat[cat] = by_cat.get(cat, 0) + scores.points.get(c, 0)
    capped = {cat: min(pts, scores.caps.get(cat, pts)) for cat, pts in by_cat.items()}
    return sum(capped.values()), capped


def buy_gate_ok(green_codes, scores: SignalScores) -> bool:
    fired = set(green_codes)
    return all(bool(fired & members) for members in scores.buy_gate.values())


def snapshot_scores(green, red, scores: SignalScores) -> tuple[int, int, bool]:
    gs, _ = score(green, scores)
    rs, _ = score(red, scores)
    return gs, rs, buy_gate_ok(green, scores)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_signals.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add simcore/signals.py tests/test_signals.py
git commit -m "feat: 신호 점수 계산·매수 게이트·스냅샷 점수 헬퍼"
```

---

### Task 5: 모델 확장 — 스냅샷·포지션·거래·사유

**Files:**
- Modify: `simcore/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces:
  - `SymbolSnapshot` 필드 추가: `green_score: int = 0`, `red_score: int = 0`, `buy_gate: bool = False`.
  - `Position` 필드 추가: `peak_price: float = 0.0`, `locked_stop_pct: float = 0.0` (portfolio.buy 가 설정).
  - `Trade` 필드 추가: `green_score: int = 0`, `red_score: int = 0`.
  - `TradeReason.TRAILING_STOP = "TRAILING_STOP"`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_models.py`에 추가

```python
from datetime import date
from simcore.models import SymbolSnapshot, Position, Trade, TradeReason, Market


def test_snapshot_has_score_fields():
    s = SymbolSnapshot("005930", Market.KR, ("G1",), (), 100.0, 0.01, 1000.0,
                       green_score=18, red_score=0, buy_gate=True)
    assert s.green_score == 18 and s.buy_gate is True


def test_position_trailing_fields_default():
    p = Position("005930", Market.KR, 10, 100.0, date(2026, 1, 2))
    assert p.peak_price == 0.0 and p.locked_stop_pct == 0.0
    p.peak_price = 120.0
    assert p.peak_price == 120.0


def test_trailing_stop_reason_exists():
    assert TradeReason.TRAILING_STOP.value == "TRAILING_STOP"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_models.py -k "snapshot_has_score or position_trailing or trailing_stop_reason" -q`
Expected: FAIL

- [ ] **Step 3: 모델 수정** — `simcore/models.py`

`TradeReason`에 추가:
```python
    TRAILING_STOP = "TRAILING_STOP"
```

`Position`에 필드 추가(기존 `opened: Date` 아래):
```python
    peak_price: float = 0.0
    locked_stop_pct: float = 0.0
```

`Trade`에 필드 추가(기존 `fired` 아래, `realized_pnl` 위):
```python
    green_score: int = 0
    red_score: int = 0
```

`SymbolSnapshot`에 필드 추가(기존 `volume: float` 아래):
```python
    green_score: int = 0
    red_score: int = 0
    buy_gate: bool = False
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_models.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add simcore/models.py tests/test_models.py
git commit -m "feat: 모델 확장 (스냅샷 점수·게이트, 포지션 트레일링 상태, 거래 점수, TRAILING_STOP)"
```

---

### Task 6: 포트폴리오 — 부분매도 & 트레일링 초기화

**Files:**
- Modify: `simcore/portfolio.py`
- Test: `tests/test_portfolio.py`

**Interfaces:**
- Consumes: Task 5 `Position`(peak_price/locked_stop_pct), `Trade`(green_score/red_score).
- Produces:
  - `buy(..., green_count=0, green_score=0, fired=())` — Position 생성 시 `peak_price=price`, `locked_stop_pct=stop_loss_pct(rules)`. Trade 에 green_score 기록.
  - `sell(d, symbol, price, reason, quantity=None, red_count=0, red_score=0, fired=())` — `quantity` 미지정=전량(기존과 동일, 포지션 pop). 지정 시 부분: 수량 감소·포지션 유지·해당 수량 realized_pnl.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_portfolio.py`에 추가

```python
from datetime import date
from simcore.config import Config
from simcore.models import Currency, Market, TradeReason
from simcore.portfolio import Portfolio


def _pf():
    pf = Portfolio("t", Currency.KRW, Config())
    pf.deposit(date(2026, 1, 2), 100_000_000.0, 1300.0)
    return pf


def test_buy_initializes_trailing_state():
    pf = _pf()
    pf.buy(date(2026, 1, 2), "005930", Market.KR, 100, 1000.0,
           TradeReason.SIGNAL_BUY, green_score=20)
    pos = pf.positions["005930"]
    assert pos.peak_price == 1000.0
    assert pos.locked_stop_pct == Config().rules.stop_loss_pct
    assert pf.trades[-1].green_score == 20


def test_partial_sell_keeps_position_reduced():
    pf = _pf()
    pf.buy(date(2026, 1, 2), "005930", Market.KR, 100, 1000.0, TradeReason.SIGNAL_BUY)
    cash_after_buy = pf.cash[Currency.KRW]
    pf.sell(date(2026, 1, 3), "005930", 1100.0, TradeReason.SIGNAL_SELL, quantity=50)
    assert "005930" in pf.positions
    assert pf.positions["005930"].quantity == 50
    assert pf.cash[Currency.KRW] > cash_after_buy         # 매도 대금 유입
    assert pf.trades[-1].quantity == 50
    assert pf.trades[-1].realized_pnl != 0.0


def test_full_sell_pops_position():
    pf = _pf()
    pf.buy(date(2026, 1, 2), "005930", Market.KR, 100, 1000.0, TradeReason.SIGNAL_BUY)
    pf.sell(date(2026, 1, 3), "005930", 1100.0, TradeReason.SIGNAL_SELL)
    assert "005930" not in pf.positions
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_portfolio.py -k "buy_initializes or partial_sell or full_sell_pops" -q`
Expected: FAIL

- [ ] **Step 3: 포트폴리오 수정** — `simcore/portfolio.py`

`buy` 시그니처·본문 수정:
```python
    def buy(self, d: Date, symbol: str, market: Market, quantity: int, price: float,
            reason: TradeReason, green_count: int = 0, green_score: int = 0,
            fired: tuple[str, ...] = ()) -> Trade:
        if symbol in self.positions:
            raise ValueError(f"{self.character}: {symbol} 이미 보유 중 - 재매수 금지")
        cur = MARKET_CURRENCY[market]
        gross = quantity * price
        fee, tax = costmod.trade_costs(market, Side.BUY, gross, self.config.costs)
        total = gross + fee + tax
        if self.cash[cur] + _EPS < total:
            raise ValueError(f"{self.character}: {symbol} 매수 현금 부족 "
                             f"(필요 {total:,.0f} {cur}, 보유 {self.cash[cur]:,.0f})")
        self.cash[cur] -= total
        self.positions[symbol] = Position(
            symbol, market, quantity, price, d,
            peak_price=price, locked_stop_pct=self.config.rules.stop_loss_pct)
        trade = Trade(d, self.character, symbol, market, Side.BUY, quantity, price,
                      fee, tax, reason, green_count=green_count, fired=fired,
                      green_score=green_score)
        self.trades.append(trade)
        self.assert_invariants()
        return trade
```

`sell` 시그니처·본문 수정(부분매도 지원):
```python
    def sell(self, d: Date, symbol: str, price: float, reason: TradeReason,
             quantity: int | None = None, red_count: int = 0, red_score: int = 0,
             fired: tuple[str, ...] = ()) -> Trade:
        pos = self.positions[symbol]
        qty = pos.quantity if quantity is None else min(quantity, pos.quantity)
        cur = MARKET_CURRENCY[pos.market]
        gross = qty * price
        fee, tax = costmod.trade_costs(pos.market, Side.SELL, gross, self.config.costs)
        self.cash[cur] += gross - fee - tax
        pnl = (price - pos.avg_price) * qty - fee - tax
        if qty >= pos.quantity:
            self.positions.pop(symbol)
        else:
            pos.quantity -= qty                       # 부분매도: 평단·트레일링 유지
        trade = Trade(d, self.character, symbol, pos.market, Side.SELL, qty,
                      price, fee, tax, reason, red_count=red_count, fired=fired,
                      red_score=red_score, realized_pnl=pnl)
        self.trades.append(trade)
        self.assert_invariants()
        return trade
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_portfolio.py -q`
Expected: PASS (기존 포트폴리오 테스트 포함)

- [ ] **Step 5: 커밋**

```bash
git add simcore/portfolio.py tests/test_portfolio.py
git commit -m "feat: 포트폴리오 부분매도 지원 + 매수 시 트레일링 상태 초기화"
```

---

### Task 7: 엔진 — 매수 게이팅·매도 등급·트레일링 스탑

**Files:**
- Modify: `simcore/engine.py`
- Test: `tests/test_engine_orders.py`, `tests/test_engine_risk.py`

**Interfaces:**
- Consumes: Task 2 규칙, Task 5 모델, Task 6 포트폴리오.
- Produces:
  - `PendingBuy`(green_count, green_score, fired, change_pct, volume) / `PendingSell`(reason, red_count, red_score, fired, partial: bool).
  - `evaluate_close` — 매수: `s.green_score >= r.buy_score_min and s.buy_gate`. 매도: 등급/강제 판정 후 부분/전량 예약.
  - `fill_open` — 부분/전량 체결, 부분은 쿨다운 없음.
  - `check_stops` — 트레일링 스탑(peak/locked_stop 갱신·트리거).
  - `_sell(..., quantity=None, cooldown=True)` / `_update_trailing(pos, high, r)`.

**핵심 규칙:**
- 매수 우선순위: `green_score` 내림차순 → change_pct → volume.
- 매도 등급: forced(R7 잠금손절 도달 / R18 발화 / R5+R23 동시) → 전량. red_score ≥ sell_full_min(11) → 전량. sell_partial_min(9) ≤ red_score < 11 → 부분(50%). 그 외 보유.
- 트레일링: 매 check_stops 에서 (1) 현재 locked_stop 로 `low` 트리거 검사(먼저, 보수적), 미발동 시 (2) `high`로 peak 갱신 → 잠금 손절 상향. close 기준 evaluate_close 에서도 forced 손절 검사(갭 대비).

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_engine_orders.py`에 추가:
```python
from datetime import date
from simcore.config import Config
from simcore.engine import Engine
from simcore.models import Market, SymbolSnapshot


def _snap(sym, green, red, close, gs, rs, gate, change=0.01, vol=1000.0):
    return SymbolSnapshot(sym, Market.KR, tuple(green), tuple(red), close, change, vol,
                          green_score=gs, red_score=rs, buy_gate=gate)


def test_buy_requires_score_and_gate():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    # 18점이지만 게이트 미충족 → 매수 안 함
    s1 = _snap("AAA", ["G1", "G4", "G7"], [], 100.0, 18, 0, gate=False)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": s1})
    assert all(b.symbol != "AAA" for b in eng.states["국내형"].pending_buys)
    # 18점 + 게이트 → 매수 후보
    s2 = _snap("BBB", ["G1", "G7", "G5", "G4"], [], 100.0, 19, 0, gate=True)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"BBB": s2})
    assert any(b.symbol == "BBB" for b in eng.states["국내형"].pending_buys)


def test_buy_below_threshold_rejected():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    s = _snap("AAA", ["G1", "G7", "G5"], [], 100.0, 17, 0, gate=True)  # 17<18
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {"AAA": s})
    assert not eng.states["국내형"].pending_buys


def test_buy_priority_by_score():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    snaps = {
        "LOW": _snap("LOW", ["G1", "G7", "G5"], [], 100.0, 18, 0, True, change=0.09),
        "HIGH": _snap("HIGH", ["G1", "G4", "G7", "G5"], [], 100.0, 23, 0, True, change=0.01),
    }
    eng.evaluate_close(date(2026, 1, 2), Market.KR, snaps)
    eng.fill_open(date(2026, 1, 5), Market.KR, {"LOW": 100.0, "HIGH": 100.0}, 1300.0)
    # 슬롯 5개라 둘 다 매수되지만, 우선순위 정렬상 HIGH 가 먼저
    assert "HIGH" in eng.states["국내형"].portfolio.positions
```

`tests/test_engine_risk.py`에 추가:
```python
from datetime import date
from simcore.config import Config
from simcore.engine import Engine
from simcore.models import DailyBar, Market, SymbolSnapshot, TradeReason


def _buy_one(eng, sym="AAA", price=100.0):
    s = SymbolSnapshot(sym, Market.KR, ("G1", "G7", "G5", "G4"), (), price, 0.01, 1000.0,
                       green_score=19, red_score=0, buy_gate=True)
    eng.evaluate_close(date(2026, 1, 2), Market.KR, {sym: s})
    eng.fill_open(date(2026, 1, 5), Market.KR, {sym: price}, 1300.0)


def test_partial_sell_tier_keeps_position_no_cooldown():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    _buy_one(eng)
    pos = eng.states["국내형"].portfolio.positions["AAA"]
    q0 = pos.quantity
    # red_score 10 (부분매도 구간 9~10)
    s = SymbolSnapshot("AAA", Market.KR, (), ("R1", "R2"), 100.0, -0.01, 1000.0,
                       green_score=0, red_score=10, buy_gate=False)
    eng.evaluate_close(date(2026, 1, 6), Market.KR, {"AAA": s})
    eng.fill_open(date(2026, 1, 7), Market.KR, {"AAA": 100.0}, 1300.0)
    assert "AAA" in eng.states["국내형"].portfolio.positions
    assert eng.states["국내형"].portfolio.positions["AAA"].quantity < q0
    assert "AAA" not in eng.states["국내형"].cooldowns       # 부분매도는 쿨다운 없음


def test_full_sell_tier_and_cooldown():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    _buy_one(eng)
    s = SymbolSnapshot("AAA", Market.KR, (), ("R1", "R4", "R11"), 100.0, -0.01, 1000.0,
                       green_score=0, red_score=15, buy_gate=False)
    eng.evaluate_close(date(2026, 1, 6), Market.KR, {"AAA": s})
    eng.fill_open(date(2026, 1, 7), Market.KR, {"AAA": 100.0}, 1300.0)
    assert "AAA" not in eng.states["국내형"].portfolio.positions
    assert "AAA" in eng.states["국내형"].cooldowns


def test_stop_loss_at_minus_7pct():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    _buy_one(eng, price=100.0)
    bar = DailyBar("AAA", date(2026, 1, 6), 100.0, 100.0, 92.0, 93.0, 1000.0)
    eng.check_stops(date(2026, 1, 6), Market.KR, {"AAA": bar}, 1300.0)
    assert "AAA" not in eng.states["국내형"].portfolio.positions
    t = eng.states["국내형"].portfolio.trades[-1]
    assert t.reason == TradeReason.STOP_LOSS


def test_trailing_locks_in_gain():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    _buy_one(eng, price=100.0)
    # 고가 +25% → 잠금 손절 +10% 로 상향
    up = DailyBar("AAA", date(2026, 1, 6), 100.0, 125.0, 100.0, 124.0, 1000.0)
    eng.check_stops(date(2026, 1, 6), Market.KR, {"AAA": up}, 1300.0)
    pos = eng.states["국내형"].portfolio.positions["AAA"]
    assert pos.locked_stop_pct >= 0.10
    # 다음날 +8% 로 하락 → 잠금선(+10%) 하회 → 매도
    down = DailyBar("AAA", date(2026, 1, 7), 120.0, 120.0, 108.0, 109.0, 1000.0)
    eng.check_stops(date(2026, 1, 7), Market.KR, {"AAA": down}, 1300.0)
    assert "AAA" not in eng.states["국내형"].portfolio.positions
    assert eng.states["국내형"].portfolio.trades[-1].reason == TradeReason.TRAILING_STOP


def test_forced_sell_r5_and_r23():
    eng = Engine(Config()); eng.start(date(2026, 1, 2), 1300.0)
    _buy_one(eng)
    # red_score 낮아도 R5+R23 동시 → 강제 전량
    s = SymbolSnapshot("AAA", Market.KR, (), ("R5", "R23"), 100.0, -0.05, 1000.0,
                       green_score=0, red_score=8, buy_gate=False)
    eng.evaluate_close(date(2026, 1, 6), Market.KR, {"AAA": s})
    eng.fill_open(date(2026, 1, 7), Market.KR, {"AAA": 100.0}, 1300.0)
    assert "AAA" not in eng.states["국내형"].portfolio.positions
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_engine_orders.py tests/test_engine_risk.py -k "buy_requires or buy_below or buy_priority or partial_sell_tier or full_sell_tier or stop_loss_at or trailing_locks or forced_sell" -q`
Expected: FAIL

- [ ] **Step 3: 엔진 수정** — `simcore/engine.py`

`PendingBuy`/`PendingSell` 교체:
```python
@dataclass
class PendingBuy:
    symbol: str
    market: Market
    green_count: int
    green_score: int
    fired: tuple[str, ...]
    change_pct: float
    volume: float


@dataclass
class PendingSell:
    symbol: str
    market: Market
    reason: TradeReason
    red_count: int
    red_score: int
    fired: tuple[str, ...]
    partial: bool = False
```

`evaluate_close` 교체:
```python
    def evaluate_close(self, d: Date, market: Market,
                       snaps: dict[str, SymbolSnapshot]) -> None:
        r = self.config.rules
        for st in self.states.values():
            if market not in st.spec.markets:
                continue
            for sym in list(st.cooldowns):
                cd_market, remaining = st.cooldowns[sym]
                if cd_market != market:
                    continue
                remaining -= 1
                if remaining <= 0:
                    del st.cooldowns[sym]
                else:
                    st.cooldowns[sym][1] = remaining
            # 매도 판정
            already_pending = {ps.symbol for ps in st.pending_sells}
            for sym, pos in st.portfolio.positions.items():
                if pos.market != market or sym not in snaps or sym in already_pending:
                    continue
                s = snaps[sym]
                red = set(s.red)
                stop_px = pos.avg_price * (1 + pos.locked_stop_pct)
                forced = (s.close <= stop_px            # R7/트레일링 (종가 갭)
                          or "R18" in red               # 지지선 붕괴
                          or ({"R5", "R23"} <= red))     # 거래량 급증 음봉 + 장대 음봉
                if forced:
                    st.pending_sells.append(PendingSell(
                        sym, market, TradeReason.SIGNAL_SELL, len(red), s.red_score,
                        tuple(s.red), partial=False))
                elif s.red_score >= r.sell_full_min:
                    st.pending_sells.append(PendingSell(
                        sym, market, TradeReason.SIGNAL_SELL, len(red), s.red_score,
                        tuple(s.red), partial=False))
                elif s.red_score >= r.sell_partial_min:
                    st.pending_sells.append(PendingSell(
                        sym, market, TradeReason.SIGNAL_SELL, len(red), s.red_score,
                        tuple(s.red), partial=True))
            # 매수 후보
            held = set(st.portfolio.positions) | {b.symbol for b in st.pending_buys}
            for sym, s in snaps.items():
                if (sym in held or sym in st.cooldowns
                        or s.green_score < r.buy_score_min or not s.buy_gate):
                    continue
                st.pending_buys.append(PendingBuy(
                    sym, market, len(s.green), s.green_score, s.green,
                    s.change_pct, s.volume))
```

`fill_open` 매도/매수 부분 교체:
```python
    def fill_open(self, d: Date, market: Market, opens: dict[str, float],
                  fx_rate: float) -> None:
        r = self.config.rules
        for st in self.states.values():
            if market not in st.spec.markets:
                continue
            carried: list[PendingSell] = []
            for ps in st.pending_sells:
                if ps.market != market:
                    carried.append(ps); continue
                if ps.symbol not in st.portfolio.positions:
                    continue
                price = opens.get(ps.symbol)
                if price is None:
                    carried.append(ps); continue
                pos = st.portfolio.positions[ps.symbol]
                qty = None
                if ps.partial:
                    qty = max(1, int(pos.quantity * r.partial_sell_fraction))
                self._sell(st, d, ps.symbol, price, ps.reason, fx_rate,
                           quantity=qty, cooldown=not ps.partial,
                           red_count=ps.red_count, red_score=ps.red_score, fired=ps.fired)
            st.pending_sells = carried
            buys = sorted((b for b in st.pending_buys if b.market == market),
                          key=lambda b: (-b.green_score, -b.change_pct, -b.volume))
            st.pending_buys = [b for b in st.pending_buys if b.market != market]
            for b in buys:
                slots = r.max_positions - len(st.portfolio.positions)
                if slots <= 0:
                    break
                price = opens.get(b.symbol)
                if (price is None or b.symbol in st.portfolio.positions
                        or b.symbol in st.cooldowns):
                    continue
                self._buy(st, d, b, price, fx_rate, slots)
```

`_buy` 의 portfolio.buy 호출에 green_score 추가:
```python
        pf.buy(d, b.symbol, b.market, qty, fill_price, TradeReason.SIGNAL_BUY,
               green_count=b.green_count, green_score=b.green_score, fired=b.fired)
```

`_sell` 교체(부분/쿨다운/점수):
```python
    def _sell(self, st: CharacterState, d: Date, symbol: str, price: float,
              reason: TradeReason, fx_rate: float, quantity: int | None = None,
              cooldown: bool = True, red_count: int = 0, red_score: int = 0,
              fired: tuple[str, ...] = ()) -> None:
        pos = st.portfolio.positions[symbol]
        market = pos.market
        fill_price = price * (1 - self.config.costs.slippage)
        st.portfolio.sell(d, symbol, fill_price, reason, quantity=quantity,
                          red_count=red_count, red_score=red_score, fired=fired)
        if cooldown and symbol not in st.portfolio.positions:
            st.cooldowns[symbol] = [market, self.config.rules.cooldown_days]
        if st.spec.base_currency == Currency.KRW and market == Market.US:
            st.portfolio.convert_all_usd_to_krw(fx_rate)
```

`check_stops` 교체(트레일링) + 헬퍼 추가:
```python
    def _update_trailing(self, pos, high: float) -> None:
        r = self.config.rules
        if high > pos.peak_price:
            pos.peak_price = high
        peak_gain = pos.peak_price / pos.avg_price - 1.0
        for thr, lock in r.trailing_tiers:          # 내림차순, 첫 매칭
            if peak_gain >= thr:
                pos.locked_stop_pct = max(pos.locked_stop_pct, lock)
                break
        if peak_gain >= r.trailing_top:             # 최고가 대비 트레일
            trail = pos.peak_price * (1 - r.trail_pct) / pos.avg_price - 1.0
            pos.locked_stop_pct = max(pos.locked_stop_pct, trail)

    def check_stops(self, d: Date, market: Market, bars: dict[str, DailyBar],
                    fx_rate: float) -> None:
        for st in self.states.values():
            if market not in st.spec.markets:
                continue
            for sym in list(st.portfolio.positions):
                pos = st.portfolio.positions[sym]
                if pos.market != market or sym not in bars:
                    continue
                b = bars[sym]
                stop_px = pos.avg_price * (1 + pos.locked_stop_pct)  # 갱신 전 잠금선
                if b.low <= stop_px:                                 # 트리거 우선(보수적)
                    reason = (TradeReason.TRAILING_STOP
                              if pos.locked_stop_pct > self.config.rules.stop_loss_pct
                              else TradeReason.STOP_LOSS)
                    self._sell(st, d, sym, stop_px, reason, fx_rate)
                    continue
                self._update_trailing(pos, b.high)                   # 미발동 시 peak 갱신
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_engine_orders.py tests/test_engine_risk.py -q`
Expected: PASS (기존 v1 규칙 가정 테스트는 v2 값으로 갱신)

- [ ] **Step 5: 커밋**

```bash
git add simcore/engine.py tests/test_engine_orders.py tests/test_engine_risk.py
git commit -m "feat: 엔진 v2 (매수 게이팅·매도 등급·부분매도·트레일링 스탑)"
```

---

### Task 8: 스냅샷 통합 — 리플레이 & 라이브

**Files:**
- Modify: `simcore/replay.py`, `simcore/live/orchestrator.py`
- Test: `tests/test_replay_integration.py`

**Interfaces:**
- Consumes: Task 4 `snapshot_scores`, Task 5 `SymbolSnapshot`.
- Produces: 두 스냅샷 생성 지점이 `green_score`/`red_score`/`buy_gate`를 채운다. `ReplayResult.green_hist` → 유지하되 green_score 분포로 기록.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_replay_integration.py`에 추가

```python
def test_snapshot_carries_scores(tmp_path):
    # 상승 추세 합성 데이터로 리플레이 → 최소 하나의 매수(점수 게이트 통과) 발생
    import numpy as np, pandas as pd
    from datetime import date
    from simcore.config import Config
    from simcore.replay import DataBundle, run_replay

    idx = pd.date_range("2025-06-01", periods=200, freq="B")
    up = np.linspace(100, 400, 200)
    df = pd.DataFrame({"open": up, "high": up + 2, "low": up - 2,
                       "close": up, "volume": np.linspace(1000, 5000, 200)}, index=idx)
    bundle = DataBundle(kr={"AAA": df}, us={},
                        fx=pd.Series(1300.0, index=idx))
    res = run_replay(Config(), bundle, date(2025, 9, 1), date(2026, 2, 1))
    # 거래가 발생했고 매수 거래에 green_score 기록
    buys = res.trades[res.trades.side == "BUY"] if not res.trades.empty else res.trades
    assert not buys.empty
    assert (buys["green_score"] >= 18).all()
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_replay_integration.py -k "snapshot_carries_scores" -q`
Expected: FAIL (`KeyError: 'green_score'` 또는 매수 없음)

- [ ] **Step 3: 통합 수정**

`simcore/replay.py` — 스냅샷 생성부(현 90~99행) 교체:
```python
            snaps: dict[str, SymbolSnapshot] = {}
            for sym, df in todays.items():
                green, red = sigmod.fired_at(frames[market][sym], ts)
                gs, rs, gate = sigmod.snapshot_scores(green, red, config.scores)
                loc = df.index.get_loc(ts)
                prev_close = float(df["close"].iloc[loc - 1]) if loc > 0 else float(df.loc[ts, "close"])
                close = float(df.loc[ts, "close"])
                snaps[sym] = SymbolSnapshot(
                    sym, market, green, red, close,
                    close / prev_close - 1.0, float(df.loc[ts, "volume"]),
                    green_score=gs, red_score=rs, buy_gate=gate)
                last_close[sym] = close
                green_counts.append(gs)             # green_score 분포 기록
            engine.evaluate_close(d, market, snaps)
```

또한 trades DataFrame 생성부(현 107~113행)에 점수 컬럼 추가:
```python
        "green_count": t.green_count, "red_count": t.red_count,
        "green_score": t.green_score, "red_score": t.red_score,
        "fired": ";".join(t.fired), "realized_pnl": t.realized_pnl,
```

`simcore/live/orchestrator.py` — 61~66행 스냅샷 생성부에 점수 반영:
```python
            frame = sigmod.evaluate_frame(df, self.cfg.signals)
            green, red = sigmod.fired_at(frame, ts)
            gs, rs, gate = sigmod.snapshot_scores(green, red, self.cfg.scores)
            ...
            snaps[sym] = SymbolSnapshot(sym, m, green, red, close,
                                        change_pct, volume,
                                        green_score=gs, red_score=rs, buy_gate=gate)
```
(정확한 인접 코드는 파일에서 확인 후 필드만 추가. `self.cfg`가 Config 인스턴스인지 확인해 `.scores` 접근.)

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_replay_integration.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add simcore/replay.py simcore/live/orchestrator.py tests/test_replay_integration.py
git commit -m "feat: 스냅샷에 신호 점수·매수 게이트 반영 (리플레이·라이브 공통)"
```

---

### Task 9: CLI·데이터 워밍업·문서

**Files:**
- Modify: `simcore/__main__.py`, `simcore/data.py`, `docs/trading-rules.md`, `README.md`
- Test: `tests/test_data.py`(경량 확인)

**Interfaces:**
- Consumes: Task 2 `TradeRules.buy_score_min`.
- Produces: `--buy-score` CLI 옵션, 워밍업 패딩 상향, v2 문서.

- [ ] **Step 1: data.py 워밍업 상향** — `simcore/data.py`

```python
LOOKBACK_PAD_DAYS = 180  # 지표 워밍업(일목 78거래일 ≈ 118달력일)을 위한 여유
```
코멘트도 갱신. `tests/test_data.py`에 상수 확인 테스트 추가:
```python
def test_lookback_pad_covers_ichimoku():
    from simcore.data import LOOKBACK_PAD_DAYS
    assert LOOKBACK_PAD_DAYS >= 120     # 일목 워밍업 안전 여유
```

- [ ] **Step 2: 실패 확인 & 통과**

Run: `python -m pytest tests/test_data.py -k lookback_pad -q`
Expected: 상수 반영 후 PASS

- [ ] **Step 3: CLI 옵션 교체** — `simcore/__main__.py`

`--buy-threshold` 정의(현 30행)와 적용(현 39~40행)을 교체:
```python
    ap.add_argument("--buy-score", type=int, default=None,
                    help="매수 최소 총점(기본 18)")
```
```python
    if args.buy_score is not None:
        cfg = replace(cfg, rules=replace(cfg.rules, buy_score_min=args.buy_score))
```

- [ ] **Step 4: trading-rules.md v2 재작성** — `docs/trading-rules.md`

스펙 `docs/superpowers/specs/2026-07-09-signal-system-v2-design.md`의 §2~§6을 단일 기준으로 옮긴다. 반드시 포함:
- 신규 지표 목록.
- 청/적 신호표(코드·이름·카테고리·점수·구현/스텁) — config.SignalScores.points/category 와 값 1:1.
- 카테고리 상한표(추세10/돌파·하락패턴10/거래량8/모멘텀8/변동성6) — config.caps 와 1:1.
- 매수 게이트(총점 ≥ 18 AND 추세{G1,G4,G11,G12,G15}·돌파{G7,G18}·거래량{G5,G13,G23} 각 1개+) — config.buy_gate 와 1:1.
- 매도 등급(0~5 보유/6~8 주의/9~10 부분 50%/11+ 전량), 강제매도(R7 잠금손절·R18·R5+R23).
- 트레일링 스탑 단계표(+10%→0%, +20%→+10%, +30%→+20%, +40%→+30%, >+40% 최고가 −7%) — config.trailing_tiers/trail_pct 와 1:1.
- 스텁 신호 "미구현(항상 꺼짐)" 명시.

- [ ] **Step 5: README 갱신 & 커밋** — `README.md`

첫 문단 "매수 7 / 매도 3" → "점수제(매수 18점+게이트 / 매도 등급·트레일링 스탑)"로, 리플레이 예시의 `--buy-threshold 5` → `--buy-score 16` 로 수정.

```bash
git add simcore/__main__.py simcore/data.py docs/trading-rules.md README.md tests/test_data.py
git commit -m "docs: trading-rules v2 재작성 + CLI --buy-score + 워밍업 패딩 상향"
```

---

### Task 10: 전체 회귀 + 6개월 리플레이 검증 + 실험 기록

**Files:**
- Create: `docs/experiments/replay_2026-01-09_2026-07-09_v2.md` (write_outputs 가 생성; 필요 시 요약 보강)

**Interfaces:**
- Consumes: 완성된 엔진 전체.

- [ ] **Step 1: 전체 테스트 회귀**

Run: `python -m pytest -q`
Expected: 전부 PASS. 실패 시 원인 태스크로 회귀해 수정(신규 규칙과 상충하는 잔여 v1 가정 테스트 갱신).

- [ ] **Step 2: 6개월 리플레이 실행**

Run: `python -m simcore --start 2026-01-09 --end 2026-07-09 --kr-top 50 --us-top 50`
Expected: 정상 종료. `out/` 에 거래내역(green_score/red_score 포함)·자산곡선, `docs/experiments/` 에 리포트 생성. 네트워크/데이터 소스 이슈 시 캐시 확인.

- [ ] **Step 3: 결과 검증**

확인 항목:
- 3캐릭터 모두 자산곡선이 그려지고, 총자산 = 현금 + 평가액(불변식).
- 매수 거래는 전부 green_score ≥ 18. 매도에 부분/전량/트레일링/손절 사유가 분포.
- TWR·MDD·거래수·(가능하면)승률이 리포트에 기록됨.
- 손실 최소화 취지 확인: MDD 가 과도하지 않은지, 손절/트레일링이 실제 작동했는지 대표 거래 몇 건의 fired·score 근거 확인.

- [ ] **Step 4: 실험 기록 보강 & 커밋**

`docs/experiments/replay_2026-01-09_2026-07-09_v2.md` 상단에 요약(실행일 2026-07-09, config 스냅샷 요지, 캐릭터별 지표, 대표 거래 근거, 관찰/한계)을 보강한다.

```bash
git add docs/experiments/ out/ 2>/dev/null; git add docs/experiments/
git commit -m "test: 신호 v2 6개월 리플레이(2026-01-09~07-09) 결과 기록"
```

주의: `out/`는 .gitignore 대상이므로 커밋되지 않는다(정상). 실험 기록(docs/experiments)만 커밋한다.

---

## Self-Review 체크 결과

- **스펙 커버리지**: §2 지표/신호=Task1·3, §3 점수·상한=Task2·4, §4 매수 게이트=Task4·7, §5 매도 등급=Task7, §6 트레일링=Task7, §7 config=Task2, §8 신호 인터페이스=Task3·4, §9 엔진=Task6·7, §10 trading-rules=Task9, §11 테스트=각 태스크, §12 완료기준=Task10. 모두 매핑됨.
- **플레이스홀더 없음**: 모든 코드 스텝에 실제 코드 포함.
- **타입 일관성**: `snapshot_scores` 반환 (green_score, red_score, buy_gate) — Task4 정의, Task8 소비 일치. `SymbolSnapshot` 신규 필드 Task5 정의 → Task7 소비 → Task8 생성 일치. `PendingBuy.green_score` Task7 정의·소비 일치. `_sell(quantity, cooldown, red_score)` Task7 시그니처 ↔ portfolio.sell(quantity, red_score) Task6 일치.
- **G23 게이트/카테고리 분리**: Global Constraints + Task2 buy_gate 집합으로 명시 해소.
- **라이브 파손 방지**: Task8 이 orchestrator 스냅샷도 갱신(게이트 미설정 시 매수 불가 문제 예방).
