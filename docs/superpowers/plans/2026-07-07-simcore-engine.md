# simcore 매매 엔진 코어 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 청신호/적신호 카운트 규칙(매수 7 / 매도 3)으로 3캐릭터가 모의매매하는 순수 Python 엔진을 만들고, 과거 데이터 리플레이로 검증한다.

**Architecture:** 이벤트 구동 코어. 신호 계산(signals)은 일봉 DataFrame에서 boolean 표를 벡터화 생성하고, 엔진(engine)은 신호 결과 스냅샷만 소비한다(DataFrame을 모름). 리플레이(replay)가 과거 데이터를 날짜 루프로 주입하며, 라이브 모드는 이후 서브프로젝트에서 같은 엔진 메서드에 실시간 이벤트를 주입한다.

**Tech Stack:** Python 3.11+, pandas, numpy, pykrx(국내 일봉), yfinance(미국 일봉·환율), pyarrow(parquet 캐시), pytest.

**스펙:** `docs/superpowers/specs/2026-07-07-simcore-engine-design.md` / 매매 규칙: `docs/trading-rules.md`

## Global Constraints

- 기준 문서: 신호 계산식·임계값·비용은 `docs/trading-rules.md` 값과 정확히 일치해야 한다.
- 모든 튜닝 파라미터는 `simcore/config.py` 의 dataclass 로만 존재. 매직 넘버 금지.
- 매수 임계값 기본 7, 매도 3, 손절 −7%, 익절 +15%, 최대 5종목, 쿨다운 2거래일.
- 비용 기본값: 국내 수수료 0.015%(매수/매도 각), 국내 거래세 0.15%(매도), 미국 수수료 0.09%, 환전 수수료 0.1%, 슬리피지 0%.
- 체결: 신호 주문은 **다음 거래일 시가**. 손절/익절은 리플레이에서 당일 OHLC 근사, **손절 우선**.
- 회계 불변식: 모든 상태 변경 후 현금 음수 금지. 수량은 정수 주.
- 수익률은 시간가중수익률(TWR). 입출금은 capital_flows 원장에 기록.
- 시크릿: `.env` 는 절대 읽지도 커밋하지도 않는다 (이번 단계에서는 KIS 키 자체를 안 씀).
- Windows 환경: 명령은 PowerShell 기준. 가상환경 `.venv` 사용, 테스트는 `.venv\Scripts\python -m pytest`.
- 커밋 메시지는 한국어 요약 + conventional commit 타입(feat/test/docs/chore).

---

### Task 1: 프로젝트 스캐폴딩 + config.py

**Files:**
- Create: `pyproject.toml`, `simcore/__init__.py`, `simcore/config.py`, `tests/__init__.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config` (필드: `signals: SignalParams`, `rules: TradeRules`, `costs: CostModel`, `initial_capital_krw: float = 100_000_000`). `dataclasses.replace` 로 오버라이드 가능. 이후 모든 태스크가 `from simcore.config import Config` 로 사용.

- [ ] **Step 1: pyproject.toml 작성**

```toml
[project]
name = "simcore"
version = "0.1.0"
description = "규칙 기반 롱온리 페이퍼 트레이딩 시뮬레이터 엔진 코어"
requires-python = ">=3.11"
dependencies = [
    "pandas>=2.0",
    "numpy>=1.26",
    "pykrx>=1.0.45",
    "yfinance>=0.2.40",
    "pyarrow>=15",
    "lxml>=5",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["simcore*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: 가상환경 생성 + 설치**

Run: `py -3.11 -m venv .venv` (없으면 `py -m venv .venv`), 이후 `.venv\Scripts\python -m pip install -e .[dev]`
Expected: `Successfully installed simcore-0.1.0 ...`

- [ ] **Step 3: 실패하는 테스트 작성** — `tests/test_config.py`

```python
from dataclasses import replace
from simcore.config import Config

def test_defaults_match_trading_rules():
    c = Config()
    assert c.rules.buy_threshold == 7
    assert c.rules.sell_threshold == 3
    assert c.rules.stop_loss_pct == -0.07
    assert c.rules.take_profit_pct == 0.15
    assert c.rules.max_positions == 5
    assert c.rules.cooldown_days == 2
    assert c.costs.kr_commission == 0.00015
    assert c.costs.kr_tax == 0.0015
    assert c.costs.us_commission == 0.0009
    assert c.costs.fx_fee == 0.001
    assert c.costs.slippage == 0.0
    assert c.initial_capital_krw == 100_000_000

def test_override_with_replace():
    c = Config()
    c2 = replace(c, rules=replace(c.rules, buy_threshold=5))
    assert c2.rules.buy_threshold == 5
    assert c.rules.buy_threshold == 7  # 원본 불변
```

- [ ] **Step 4: 실패 확인**

Run: `.venv\Scripts\python -m pytest tests\test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'simcore.config'`)

- [ ] **Step 5: 구현** — `simcore/config.py` (그리고 빈 `simcore/__init__.py`, `tests/__init__.py`)

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


@dataclass(frozen=True)
class TradeRules:
    buy_threshold: int = 7
    sell_threshold: int = 3
    stop_loss_pct: float = -0.07
    take_profit_pct: float = 0.15
    max_positions: int = 5
    cooldown_days: int = 2


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
    rules: TradeRules = field(default_factory=TradeRules)
    costs: CostModel = field(default_factory=CostModel)
    initial_capital_krw: float = 100_000_000.0
```

- [ ] **Step 6: 통과 확인**

Run: `.venv\Scripts\python -m pytest tests\test_config.py -v`
Expected: 2 passed

- [ ] **Step 7: 커밋**

```powershell
git add pyproject.toml simcore tests
git commit -m "feat: 프로젝트 스캐폴딩 + config 파라미터 정의"
```

---

### Task 2: models.py — 도메인 모델

**Files:**
- Create: `simcore/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces:
  - `Market` (Enum: `KR`, `US`), `Currency` (Enum: `KRW`, `USD`), `MARKET_CURRENCY: dict[Market, Currency]`
  - `Side` (Enum: `BUY`, `SELL`), `TradeReason` (Enum: `SIGNAL_BUY`, `SIGNAL_SELL`, `STOP_LOSS`, `TAKE_PROFIT`, `USER_WITHDRAWAL`, `DELISTED`)
  - `DailyBar(symbol, date, open, high, low, close, volume)` frozen dataclass
  - `Position(symbol, market, quantity: int, avg_price: float, opened: date)` dataclass
  - `Trade(date, character, symbol, market, side, quantity, price, fee, tax, reason, green_count=0, red_count=0, fired=(), realized_pnl=0.0)` frozen dataclass — `price`, `realized_pnl` 은 시장 통화 기준
  - `CapitalFlow(date, character, amount_krw, fx_rate)` frozen dataclass — 입금 +, 출금 −
  - `SymbolSnapshot(symbol, market, green: tuple[str, ...], red: tuple[str, ...], close, change_pct, volume)` frozen dataclass — 엔진이 소비하는 "종목 하루 신호 결과"

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_models.py`

```python
from datetime import date
from simcore.models import (
    Market, Currency, MARKET_CURRENCY, Side, TradeReason,
    DailyBar, Position, Trade, CapitalFlow, SymbolSnapshot,
)

def test_market_currency_mapping():
    assert MARKET_CURRENCY[Market.KR] == Currency.KRW
    assert MARKET_CURRENCY[Market.US] == Currency.USD

def test_trade_is_immutable_record():
    t = Trade(date=date(2025, 1, 2), character="국내형", symbol="005930",
              market=Market.KR, side=Side.BUY, quantity=10, price=60000.0,
              fee=90.0, tax=0.0, reason=TradeReason.SIGNAL_BUY,
              green_count=7, fired=("G1", "G2"))
    assert t.realized_pnl == 0.0
    assert t.fired == ("G1", "G2")

def test_snapshot_carries_signal_results():
    s = SymbolSnapshot(symbol="AAPL", market=Market.US, green=("G1",), red=(),
                       close=190.0, change_pct=0.012, volume=1_000_000)
    assert len(s.green) == 1
```

- [ ] **Step 2: 실패 확인**

Run: `.venv\Scripts\python -m pytest tests\test_models.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: 구현** — `simcore/models.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import date as Date
from enum import Enum


class Market(str, Enum):
    KR = "KR"
    US = "US"


class Currency(str, Enum):
    KRW = "KRW"
    USD = "USD"


MARKET_CURRENCY: dict[Market, Currency] = {Market.KR: Currency.KRW, Market.US: Currency.USD}


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradeReason(str, Enum):
    SIGNAL_BUY = "SIGNAL_BUY"
    SIGNAL_SELL = "SIGNAL_SELL"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    USER_WITHDRAWAL = "USER_WITHDRAWAL"
    DELISTED = "DELISTED"


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    date: Date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Position:
    symbol: str
    market: Market
    quantity: int
    avg_price: float  # 시장 통화 기준
    opened: Date


@dataclass(frozen=True)
class Trade:
    date: Date
    character: str
    symbol: str
    market: Market
    side: Side
    quantity: int
    price: float  # 시장 통화
    fee: float
    tax: float
    reason: TradeReason
    green_count: int = 0
    red_count: int = 0
    fired: tuple[str, ...] = ()
    realized_pnl: float = 0.0  # 시장 통화, 비용 차감 후


@dataclass(frozen=True)
class CapitalFlow:
    date: Date
    character: str
    amount_krw: float  # 입금 +, 출금 −
    fx_rate: float


@dataclass(frozen=True)
class SymbolSnapshot:
    """장 마감 후 종목 하나의 신호 판정 결과. 엔진은 이것만 소비한다."""
    symbol: str
    market: Market
    green: tuple[str, ...]
    red: tuple[str, ...]  # 시장 데이터 기반 R1~R6, R8, R9 (R7/R10 은 엔진이 포지션 기준으로 추가)
    close: float
    change_pct: float
    volume: float
```

- [ ] **Step 4: 통과 확인**

Run: `.venv\Scripts\python -m pytest tests\test_models.py -v` — Expected: 3 passed

- [ ] **Step 5: 커밋**

```powershell
git add simcore\models.py tests\test_models.py
git commit -m "feat: 도메인 모델 (Market/Trade/Position/CapitalFlow/SymbolSnapshot)"
```

---

### Task 3: indicators.py — 기술 지표

**Files:**
- Create: `simcore/indicators.py`
- Test: `tests/test_indicators.py`

**Interfaces:**
- Produces (모두 `pd.Series` 입력/출력, 인덱스 보존):
  - `sma(series, period) -> pd.Series`
  - `rsi(close, period=14) -> pd.Series` (Wilder 평활)
  - `macd(close, fast=12, slow=26, signal=9) -> tuple[pd.Series, pd.Series]` (macd선, 시그널선)
  - `bollinger(close, period=20, num_std=2.0) -> tuple[pd.Series, pd.Series, pd.Series]` (중심, 상단, 하단)
  - `stochastic(high, low, close, k_period=14, k_smooth=3, d_period=3) -> tuple[pd.Series, pd.Series]` (%K, %D)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_indicators.py`

```python
import numpy as np
import pandas as pd
import pytest
from simcore import indicators as ind

def test_sma_hand_computed():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    out = ind.sma(s, 3)
    assert np.isnan(out.iloc[1])
    assert out.iloc[2] == pytest.approx(2.0)
    assert out.iloc[4] == pytest.approx(4.0)

def test_rsi_all_gains_is_100():
    s = pd.Series(np.linspace(100, 200, 40))
    out = ind.rsi(s, 14)
    assert out.iloc[-1] == pytest.approx(100.0)

def test_rsi_all_losses_is_0():
    s = pd.Series(np.linspace(200, 100, 40))
    out = ind.rsi(s, 14)
    assert out.iloc[-1] == pytest.approx(0.0, abs=1e-6)

def test_macd_flat_series_is_zero():
    s = pd.Series([100.0] * 60)
    line, sig = ind.macd(s)
    assert line.iloc[-1] == pytest.approx(0.0)
    assert sig.iloc[-1] == pytest.approx(0.0)

def test_bollinger_constant_series_bands_collapse():
    s = pd.Series([50.0] * 30)
    mid, up, lo = ind.bollinger(s, 20, 2.0)
    assert mid.iloc[-1] == up.iloc[-1] == lo.iloc[-1] == pytest.approx(50.0)

def test_stochastic_close_at_high_is_100():
    n = 30
    high = pd.Series(np.arange(n) + 10.0)
    low = high - 5.0
    close = high.copy()  # 항상 고가 마감
    k, d = ind.stochastic(high, low, close)
    assert k.iloc[-1] == pytest.approx(100.0)
    assert d.iloc[-1] == pytest.approx(100.0)
```

- [ ] **Step 2: 실패 확인** — Run: `.venv\Scripts\python -m pytest tests\test_indicators.py -v` — Expected: FAIL

- [ ] **Step 3: 구현** — `simcore/indicators.py`

```python
"""기술 지표. 모든 함수는 pd.Series 를 받아 인덱스를 보존한 Series 를 반환한다."""
from __future__ import annotations
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    out = 100 - 100 / (1 + avg_gain / avg_loss)
    # 손실이 전혀 없으면 0/0 → NaN 이 되므로 100 으로 보정 (워밍업 NaN 은 유지)
    no_loss = (avg_loss == 0) & avg_gain.notna()
    out[no_loss] = 100.0
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26,
         signal: int = 9) -> tuple[pd.Series, pd.Series]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig


def bollinger(close: pd.Series, period: int = 20,
              num_std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    return mid, mid + num_std * std, mid - num_std * std


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
               k_period: int = 14, k_smooth: int = 3,
               d_period: int = 3) -> tuple[pd.Series, pd.Series]:
    ll = low.rolling(k_period).min()
    hh = high.rolling(k_period).max()
    raw_k = 100 * (close - ll) / (hh - ll)
    k = raw_k.rolling(k_smooth).mean()
    d = k.rolling(d_period).mean()
    return k, d
```

- [ ] **Step 4: 통과 확인** — Run: `.venv\Scripts\python -m pytest tests\test_indicators.py -v` — Expected: 6 passed

- [ ] **Step 5: 커밋**

```powershell
git add simcore\indicators.py tests\test_indicators.py
git commit -m "feat: 기술 지표 (SMA/RSI/MACD/볼린저/스토캐스틱)"
```

---

### Task 4: signals.py — 신호 판정 (벡터화)

**Files:**
- Create: `simcore/signals.py`
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes: `simcore.indicators`, `SignalParams`
- Produces:
  - `GREEN_COLS = ["G1",...,"G10"]`, `RED_COLS = ["R1",...,"R6","R8","R9"]` (R7/R10 은 포지션 의존이라 엔진 담당)
  - `min_history(p: SignalParams) -> int` — 신호 판정에 필요한 최소 일봉 수 (기본 파라미터에서 61)
  - `evaluate_frame(df: pd.DataFrame, p: SignalParams) -> pd.DataFrame` — 입력 df 컬럼: `open/high/low/close/volume`, 날짜 오름차순 인덱스. 반환: 같은 인덱스에 GREEN_COLS+RED_COLS boolean 컬럼. 히스토리 부족 구간은 전부 False. **G8/G9/R8/R9 컬럼은 존재하되 항상 False (감정·수급 스텁 — 4단계에서 이 컬럼을 OR 로 대체)**
  - `fired_at(frame: pd.DataFrame, d) -> tuple[tuple[str, ...], tuple[str, ...]]` — 해당 날짜에 켜진 (green ids, red ids)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_signals.py`

합성 시계열로 신호가 정확한 날 켜지는지 검증한다. 헬퍼로 OHLCV DataFrame 생성기를 둔다.

```python
import numpy as np
import pandas as pd
from simcore.config import SignalParams
from simcore.signals import evaluate_frame, fired_at, min_history, GREEN_COLS, RED_COLS

P = SignalParams()

def make_df(closes, volumes=None, opens=None, highs=None, lows=None):
    n = len(closes)
    closes = pd.Series(closes, dtype=float)
    idx = pd.bdate_range("2024-01-02", periods=n)
    df = pd.DataFrame({
        "open": opens if opens is not None else closes.values,
        "high": highs if highs is not None else closes.values * 1.01,
        "low": lows if lows is not None else closes.values * 0.99,
        "close": closes.values,
        "volume": volumes if volumes is not None else np.full(n, 1000.0),
    }, index=idx)
    return df

def test_insufficient_history_all_false():
    df = make_df(np.linspace(100, 110, 30))  # 61봉 미만
    frame = evaluate_frame(df, P)
    assert not frame.iloc[-1].any()

def test_uptrend_fires_g1_g2_g4_and_not_r1_r2():
    df = make_df(np.linspace(100, 160, 100))  # 꾸준한 상승
    green, red = fired_at(evaluate_frame(df, P), df.index[-1])
    assert {"G1", "G2", "G4"} <= set(green)
    assert "R1" not in red and "R2" not in red

def test_downtrend_fires_r1_r2_r4():
    df = make_df(np.linspace(160, 100, 100))
    green, red = fired_at(evaluate_frame(df, P), df.index[-1])
    assert {"R1", "R2", "R4"} <= set(red)

def test_g5_volume_surge_bullish_candle():
    closes = np.full(100, 100.0)
    volumes = np.full(100, 1000.0)
    volumes[-1] = 2000.0                     # 평균의 2배
    opens = closes.copy(); opens[-1] = 99.0  # 양봉 (종가 100 > 시가 99)
    df = make_df(closes, volumes=volumes, opens=opens)
    green, red = fired_at(evaluate_frame(df, P), df.index[-1])
    assert "G5" in green
    assert "R5" not in red

def test_g7_breakout_over_60d_high():
    closes = np.concatenate([np.full(80, 100.0), [105.0]])  # 마지막 날 신고가
    df = make_df(closes)
    green, _ = fired_at(evaluate_frame(df, P), df.index[-1])
    assert "G7" in green

def test_stub_columns_always_false():
    df = make_df(np.linspace(100, 160, 100))
    frame = evaluate_frame(df, P)
    for col in ["G8", "G9", "R8", "R9"]:
        assert col in frame.columns
        assert not frame[col].any()

def test_min_history_default_is_61():
    assert min_history(P) == 61
```

- [ ] **Step 2: 실패 확인** — Run: `.venv\Scripts\python -m pytest tests\test_signals.py -v` — Expected: FAIL

- [ ] **Step 3: 구현** — `simcore/signals.py`

```python
"""청/적신호 판정. 계산식은 docs/trading-rules.md 2·3장과 1:1 대응.
G8/G9/R8/R9(감정·수급)는 스텁 — 항상 False 컬럼으로 존재하며 4단계에서 대체된다.
R7(손절)/R10(익절)은 포지션 평단가에 의존하므로 engine 이 판정한다."""
from __future__ import annotations
import pandas as pd

from simcore.config import SignalParams
from simcore import indicators as ind

GREEN_COLS = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10"]
RED_COLS = ["R1", "R2", "R3", "R4", "R5", "R6", "R8", "R9"]


def min_history(p: SignalParams) -> int:
    return max(
        p.breakout_lookback + 1,
        p.sma_slow + 1,
        p.macd_slow + p.macd_signal,
        p.bb_period + 1,
        p.rsi_period + 2,
        p.stoch_k + p.stoch_k_smooth + p.stoch_d,
    )


def evaluate_frame(df: pd.DataFrame, p: SignalParams) -> pd.DataFrame:
    close, open_, high, low, vol = df["close"], df["open"], df["high"], df["low"], df["volume"]
    sma_f = ind.sma(close, p.sma_fast)
    sma_s = ind.sma(close, p.sma_slow)
    rsi = ind.rsi(close, p.rsi_period)
    macd_line, macd_sig = ind.macd(close, p.macd_fast, p.macd_slow, p.macd_signal)
    bb_mid, bb_up, bb_lo = ind.bollinger(close, p.bb_period, p.bb_std)
    k, d = ind.stochastic(high, low, close, p.stoch_k, p.stoch_k_smooth, p.stoch_d)
    vol_avg = ind.sma(vol, p.volume_avg_period)

    surge = vol >= vol_avg * p.volume_surge_ratio
    prev_high = close.rolling(p.breakout_lookback).max().shift(1)  # 당일 제외 직전 N일 최고 종가

    out = pd.DataFrame(index=df.index)
    out["G1"] = sma_f > sma_s
    out["G2"] = close > sma_s
    out["G3"] = (rsi.shift(1) <= p.rsi_buy_cross) & (rsi > p.rsi_buy_cross)
    out["G4"] = macd_line > macd_sig
    out["G5"] = surge & (close > open_)
    out["G6"] = (close.shift(1) <= bb_mid.shift(1)) & (close > bb_mid)
    out["G7"] = close > prev_high
    out["G8"] = False   # 스텁: 긍정 심리 급증
    out["G9"] = False   # 스텁: 외인·기관 순매수
    out["G10"] = (k.shift(1) < p.stoch_oversold) & (k.shift(1) <= d.shift(1)) & (k > d)

    out["R1"] = sma_f < sma_s
    out["R2"] = close < sma_s
    out["R3"] = (rsi.shift(1) >= p.rsi_overbought) & (rsi < rsi.shift(1))
    out["R4"] = macd_line < macd_sig
    out["R5"] = surge & (close < open_)
    out["R6"] = close < bb_lo
    out["R8"] = False   # 스텁: 부정 심리 급증
    out["R9"] = False   # 스텁: 외인·기관 순매도

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

- [ ] **Step 4: 통과 확인** — Run: `.venv\Scripts\python -m pytest tests\test_signals.py -v` — Expected: 8 passed

- [ ] **Step 5: 전체 테스트 + 커밋**

Run: `.venv\Scripts\python -m pytest -q` — Expected: all passed

```powershell
git add simcore\signals.py tests\test_signals.py
git commit -m "feat: 청/적신호 벡터화 판정 (G1~G10, R1~R6, 스텁 컬럼 포함)"
```

---

### Task 5: costs.py — 비용 모델

**Files:**
- Create: `simcore/costs.py`
- Test: `tests/test_costs.py`

**Interfaces:**
- Consumes: `CostModel`, `Market`, `Side`
- Produces:
  - `trade_costs(market: Market, side: Side, gross: float, c: CostModel) -> tuple[float, float]` — (수수료, 세금)
  - `krw_to_usd(amount_krw, fx_rate, fee_rate) -> float` / `usd_to_krw(amount_usd, fx_rate, fee_rate) -> float` — 환전 수수료 차감 후 금액
  - `commission_rate(market: Market, c: CostModel) -> float`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_costs.py`

```python
import pytest
from simcore.config import CostModel
from simcore.models import Market, Side
from simcore.costs import trade_costs, krw_to_usd, usd_to_krw, commission_rate

C = CostModel()

def test_kr_buy_has_fee_no_tax():
    fee, tax = trade_costs(Market.KR, Side.BUY, 1_000_000, C)
    assert fee == pytest.approx(150.0)   # 0.015%
    assert tax == 0.0

def test_kr_sell_has_fee_and_tax():
    fee, tax = trade_costs(Market.KR, Side.SELL, 1_000_000, C)
    assert fee == pytest.approx(150.0)
    assert tax == pytest.approx(1500.0)  # 0.15%

def test_us_sell_has_fee_only():
    fee, tax = trade_costs(Market.US, Side.SELL, 10_000, C)
    assert fee == pytest.approx(9.0)     # 0.09%
    assert tax == 0.0

def test_fx_roundtrip_loses_fee_twice():
    usd = krw_to_usd(1_300_000, 1300.0, C.fx_fee)
    assert usd == pytest.approx(1000 * 0.999)
    krw = usd_to_krw(usd, 1300.0, C.fx_fee)
    assert krw == pytest.approx(1_300_000 * 0.999 * 0.999)

def test_commission_rate():
    assert commission_rate(Market.KR, C) == C.kr_commission
    assert commission_rate(Market.US, C) == C.us_commission
```

- [ ] **Step 2: 실패 확인** — Run: `.venv\Scripts\python -m pytest tests\test_costs.py -v` — Expected: FAIL

- [ ] **Step 3: 구현** — `simcore/costs.py`

```python
"""수수료·세금·환전 비용. 요율은 config.CostModel 에서만 온다."""
from __future__ import annotations
from simcore.config import CostModel
from simcore.models import Market, Side


def commission_rate(market: Market, c: CostModel) -> float:
    return c.kr_commission if market == Market.KR else c.us_commission


def trade_costs(market: Market, side: Side, gross: float, c: CostModel) -> tuple[float, float]:
    fee = gross * commission_rate(market, c)
    tax = gross * c.kr_tax if (market == Market.KR and side == Side.SELL) else 0.0
    return fee, tax


def krw_to_usd(amount_krw: float, fx_rate: float, fee_rate: float) -> float:
    return amount_krw / fx_rate * (1 - fee_rate)


def usd_to_krw(amount_usd: float, fx_rate: float, fee_rate: float) -> float:
    return amount_usd * fx_rate * (1 - fee_rate)
```

- [ ] **Step 4: 통과 확인** — Run: `.venv\Scripts\python -m pytest tests\test_costs.py -v` — Expected: 5 passed

- [ ] **Step 5: 커밋**

```powershell
git add simcore\costs.py tests\test_costs.py
git commit -m "feat: 비용 모델 (수수료/거래세/환전)"
```

---

### Task 6: portfolio.py — 회계·입출금

**Files:**
- Create: `simcore/portfolio.py`
- Test: `tests/test_portfolio.py`

**Interfaces:**
- Consumes: `Config`, models, `costs`
- Produces:
  - `InsufficientCashError(character, shortfall_krw)` — 출금 부족 시. `shortfall_krw` 속성 보유
  - `Portfolio(character: str, base_currency: Currency, config: Config)`
    - `.cash: dict[Currency, float]`, `.positions: dict[str, Position]`, `.trades: list[Trade]`, `.flows: list[CapitalFlow]`
    - `.deposit(d, amount_krw, fx_rate)` — base 가 USD 면 환전(수수료) 후 입금
    - `.withdraw(d, amount_krw, fx_rate)` — 부족 시 `InsufficientCashError`
    - `.buy(d, symbol, market, quantity, price, reason, green_count=0, fired=()) -> Trade` — 현금(시장 통화) 부족 시 `ValueError`
    - `.sell(d, symbol, price, reason, red_count=0, fired=()) -> Trade` — 전량 매도, `realized_pnl` 계산
    - `.convert_to_usd(target_usd, fx_rate)` / `.convert_all_usd_to_krw(fx_rate)` — 범용형 환전
    - `.equity_krw(prices: dict[str, float], fx_rate) -> float` — 가격 없으면 avg_price 로 평가
    - `.assert_invariants()` — 현금 음수 금지 검사 (buy/sell/withdraw 후 내부 호출)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_portfolio.py`

```python
from datetime import date
import pytest
from simcore.config import Config
from simcore.models import Market, Currency, TradeReason, Side
from simcore.portfolio import Portfolio, InsufficientCashError

CFG = Config()
D = date(2025, 1, 6)

def krw_portfolio(cash=10_000_000):
    p = Portfolio("국내형", Currency.KRW, CFG)
    p.deposit(D, cash, fx_rate=1300.0)
    return p

def test_buy_deducts_cash_and_fee():
    p = krw_portfolio()
    t = p.buy(D, "005930", Market.KR, 100, 60000.0, TradeReason.SIGNAL_BUY, green_count=7)
    gross = 100 * 60000.0
    assert p.cash[Currency.KRW] == pytest.approx(10_000_000 - gross - gross * 0.00015)
    assert p.positions["005930"].quantity == 100
    assert t.side == Side.BUY and t.green_count == 7

def test_buy_insufficient_cash_raises():
    p = krw_portfolio(cash=1_000_000)
    with pytest.raises(ValueError):
        p.buy(D, "005930", Market.KR, 100, 60000.0, TradeReason.SIGNAL_BUY)

def test_sell_realizes_pnl_after_costs():
    p = krw_portfolio()
    p.buy(D, "005930", Market.KR, 100, 60000.0, TradeReason.SIGNAL_BUY)
    t = p.sell(date(2025, 1, 10), "005930", 66000.0, TradeReason.TAKE_PROFIT)
    gross = 100 * 66000.0
    fee, tax = gross * 0.00015, gross * 0.0015
    assert t.realized_pnl == pytest.approx(100 * 6000.0 - fee - tax)
    assert "005930" not in p.positions

def test_accounting_invariant_cash_plus_positions():
    p = krw_portfolio()
    p.buy(D, "005930", Market.KR, 100, 60000.0, TradeReason.SIGNAL_BUY)
    eq = p.equity_krw({"005930": 60000.0}, fx_rate=1300.0)
    gross = 100 * 60000.0
    assert eq == pytest.approx(10_000_000 - gross * 0.00015)  # 총자산 = 초기 - 수수료

def test_usd_base_deposit_converts():
    p = Portfolio("해외형", Currency.USD, CFG)
    p.deposit(D, 1_300_000, fx_rate=1300.0)
    assert p.cash[Currency.USD] == pytest.approx(1000 * 0.999)
    assert p.cash[Currency.KRW] == 0.0

def test_withdraw_insufficient_raises_with_shortfall():
    p = krw_portfolio(cash=1_000_000)
    with pytest.raises(InsufficientCashError) as e:
        p.withdraw(D, 3_000_000, fx_rate=1300.0)
    assert e.value.shortfall_krw == pytest.approx(2_000_000)
    assert len(p.flows) == 1  # 실패한 출금은 원장에 남지 않음 (입금 1건만)

def test_flows_ledger_records_deposit_and_withdrawal():
    p = krw_portfolio()
    p.withdraw(D, 2_000_000, fx_rate=1300.0)
    assert [f.amount_krw for f in p.flows] == [10_000_000, -2_000_000]
    assert p.cash[Currency.KRW] == pytest.approx(8_000_000)
```

- [ ] **Step 2: 실패 확인** — Run: `.venv\Scripts\python -m pytest tests\test_portfolio.py -v` — Expected: FAIL

- [ ] **Step 3: 구현** — `simcore/portfolio.py`

```python
"""캐릭터별 회계: 현금(통화별)·포지션·거래·입출금 원장. 모든 변경 후 불변식 검사."""
from __future__ import annotations
from datetime import date as Date

from simcore.config import Config
from simcore import costs as costmod
from simcore.models import (
    CapitalFlow, Currency, Market, MARKET_CURRENCY, Position, Side, Trade, TradeReason,
)

_EPS = 1e-6


class InsufficientCashError(Exception):
    def __init__(self, character: str, shortfall_krw: float):
        self.character = character
        self.shortfall_krw = shortfall_krw
        super().__init__(
            f"{character}: 출금 부족액 {shortfall_krw:,.0f} KRW — 청산할 종목을 지정하세요")


class Portfolio:
    def __init__(self, character: str, base_currency: Currency, config: Config):
        self.character = character
        self.base_currency = base_currency
        self.config = config
        self.cash: dict[Currency, float] = {Currency.KRW: 0.0, Currency.USD: 0.0}
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.flows: list[CapitalFlow] = []

    # ---- 입출금 ----
    def deposit(self, d: Date, amount_krw: float, fx_rate: float) -> None:
        if self.base_currency == Currency.USD:
            self.cash[Currency.USD] += costmod.krw_to_usd(
                amount_krw, fx_rate, self.config.costs.fx_fee)
        else:
            self.cash[Currency.KRW] += amount_krw
        self.flows.append(CapitalFlow(d, self.character, amount_krw, fx_rate))
        self.assert_invariants()

    def withdraw(self, d: Date, amount_krw: float, fx_rate: float) -> None:
        if self.base_currency == Currency.USD:
            needed_usd = amount_krw / (fx_rate * (1 - self.config.costs.fx_fee))
            if self.cash[Currency.USD] + _EPS < needed_usd:
                short = (needed_usd - self.cash[Currency.USD]) * fx_rate
                raise InsufficientCashError(self.character, short)
            self.cash[Currency.USD] -= needed_usd
        else:
            if self.cash[Currency.KRW] + _EPS < amount_krw:
                raise InsufficientCashError(
                    self.character, amount_krw - self.cash[Currency.KRW])
            self.cash[Currency.KRW] -= amount_krw
        self.flows.append(CapitalFlow(d, self.character, -amount_krw, fx_rate))
        self.assert_invariants()

    # ---- 매매 ----
    def buy(self, d: Date, symbol: str, market: Market, quantity: int, price: float,
            reason: TradeReason, green_count: int = 0,
            fired: tuple[str, ...] = ()) -> Trade:
        cur = MARKET_CURRENCY[market]
        gross = quantity * price
        fee, tax = costmod.trade_costs(market, Side.BUY, gross, self.config.costs)
        total = gross + fee + tax
        if self.cash[cur] + _EPS < total:
            raise ValueError(f"{self.character}: {symbol} 매수 현금 부족 "
                             f"(필요 {total:,.0f} {cur}, 보유 {self.cash[cur]:,.0f})")
        self.cash[cur] -= total
        self.positions[symbol] = Position(symbol, market, quantity, price, d)
        trade = Trade(d, self.character, symbol, market, Side.BUY, quantity, price,
                      fee, tax, reason, green_count=green_count, fired=fired)
        self.trades.append(trade)
        self.assert_invariants()
        return trade

    def sell(self, d: Date, symbol: str, price: float, reason: TradeReason,
             red_count: int = 0, fired: tuple[str, ...] = ()) -> Trade:
        pos = self.positions.pop(symbol)
        cur = MARKET_CURRENCY[pos.market]
        gross = pos.quantity * price
        fee, tax = costmod.trade_costs(pos.market, Side.SELL, gross, self.config.costs)
        self.cash[cur] += gross - fee - tax
        pnl = (price - pos.avg_price) * pos.quantity - fee - tax
        trade = Trade(d, self.character, symbol, pos.market, Side.SELL, pos.quantity,
                      price, fee, tax, reason, red_count=red_count, fired=fired,
                      realized_pnl=pnl)
        self.trades.append(trade)
        self.assert_invariants()
        return trade

    # ---- 환전 (범용형: KRW 베이스로 미국 주식 거래 시) ----
    def convert_to_usd(self, target_usd: float, fx_rate: float) -> None:
        fee = self.config.costs.fx_fee
        krw_cost = target_usd * fx_rate / (1 - fee)
        if self.cash[Currency.KRW] + _EPS < krw_cost:
            raise ValueError(f"{self.character}: 환전 원화 부족")
        self.cash[Currency.KRW] -= krw_cost
        self.cash[Currency.USD] += target_usd
        self.assert_invariants()

    def convert_all_usd_to_krw(self, fx_rate: float) -> None:
        usd = self.cash[Currency.USD]
        if usd <= 0:
            return
        self.cash[Currency.USD] = 0.0
        self.cash[Currency.KRW] += costmod.usd_to_krw(usd, fx_rate, self.config.costs.fx_fee)
        self.assert_invariants()

    # ---- 평가 ----
    def equity_krw(self, prices: dict[str, float], fx_rate: float) -> float:
        total = self.cash[Currency.KRW] + self.cash[Currency.USD] * fx_rate
        for sym, pos in self.positions.items():
            px = prices.get(sym, pos.avg_price)
            value = pos.quantity * px
            total += value * fx_rate if pos.market == Market.US else value
        return total

    def assert_invariants(self) -> None:
        for cur, amt in self.cash.items():
            assert amt >= -_EPS, f"{self.character}: {cur} 현금 음수 ({amt})"
        for pos in self.positions.values():
            assert pos.quantity > 0, f"{self.character}: {pos.symbol} 수량 0 이하"
```

- [ ] **Step 4: 통과 확인** — Run: `.venv\Scripts\python -m pytest tests\test_portfolio.py -v` — Expected: 7 passed

- [ ] **Step 5: 커밋**

```powershell
git add simcore\portfolio.py tests\test_portfolio.py
git commit -m "feat: 포트폴리오 회계 (매매/입출금/환전/불변식)"
```

---

### Task 7: metrics.py — TWR·성과 지표

**Files:**
- Create: `simcore/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Produces:
  - `time_weighted_return(equity: pd.Series, flows: pd.Series | None = None) -> float` — equity 는 일자별 마감 총자산(KRW), flows 는 일자별 순입출금(당일 장 시작 전 반영 가정). 첫 행은 시작 기준점
  - `max_drawdown(equity: pd.Series) -> float` (음수)
  - `simple_pnl_krw(equity: pd.Series, flows: pd.Series | None) -> float` — 누적 손익 금액 = 기말자산 − 기초자산 − 순입출금 합

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_metrics.py`

```python
import pandas as pd
import pytest
from simcore.metrics import time_weighted_return, max_drawdown, simple_pnl_krw

IDX = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])

def test_twr_without_flows_equals_simple_return():
    eq = pd.Series([100.0, 110.0, 121.0], index=IDX)
    assert time_weighted_return(eq) == pytest.approx(0.21)

def test_twr_ignores_deposit_distortion():
    # 실력은 0% 인데 둘째 날 100 입금 → 단순 수익률은 +100%, TWR 은 0% 여야 함
    eq = pd.Series([100.0, 200.0, 200.0], index=IDX)
    flows = pd.Series([0.0, 100.0, 0.0], index=IDX)
    assert time_weighted_return(eq, flows) == pytest.approx(0.0)

def test_twr_ignores_withdrawal_distortion():
    eq = pd.Series([100.0, 50.0, 50.0], index=IDX)
    flows = pd.Series([0.0, -50.0, 0.0], index=IDX)
    assert time_weighted_return(eq, flows) == pytest.approx(0.0)

def test_max_drawdown():
    eq = pd.Series([100.0, 120.0, 90.0, 110.0],
                   index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]))
    assert max_drawdown(eq) == pytest.approx(-0.25)  # 120 → 90

def test_simple_pnl_subtracts_net_flows():
    eq = pd.Series([100.0, 200.0, 210.0], index=IDX)
    flows = pd.Series([0.0, 100.0, 0.0], index=IDX)
    assert simple_pnl_krw(eq, flows) == pytest.approx(10.0)
```

- [ ] **Step 2: 실패 확인** — Run: `.venv\Scripts\python -m pytest tests\test_metrics.py -v` — Expected: FAIL

- [ ] **Step 3: 구현** — `simcore/metrics.py`

```python
"""성과 지표. 입출금 왜곡을 제거한 시간가중수익률(TWR)이 기본 수익률이다."""
from __future__ import annotations
import pandas as pd


def time_weighted_return(equity: pd.Series, flows: pd.Series | None = None) -> float:
    eq = equity.dropna()
    if len(eq) < 2:
        return 0.0
    if flows is None:
        f = pd.Series(0.0, index=eq.index)
    else:
        f = flows.reindex(eq.index).fillna(0.0)
    twr = 1.0
    prev = eq.iloc[0]
    for d in eq.index[1:]:
        base = prev + f.loc[d]  # 입출금은 당일 장 시작 전 반영
        if base > 0:
            twr *= eq.loc[d] / base
        prev = eq.loc[d]
    return twr - 1.0


def max_drawdown(equity: pd.Series) -> float:
    eq = equity.dropna()
    if len(eq) < 2:
        return 0.0
    dd = eq / eq.cummax() - 1.0
    return float(dd.min())


def simple_pnl_krw(equity: pd.Series, flows: pd.Series | None = None) -> float:
    eq = equity.dropna()
    if len(eq) < 2:
        return 0.0
    net_flows = 0.0
    if flows is not None:
        net_flows = float(flows.reindex(eq.index[1:]).fillna(0.0).sum())
    return float(eq.iloc[-1] - eq.iloc[0] - net_flows)
```

- [ ] **Step 4: 통과 확인** — Run: `.venv\Scripts\python -m pytest tests\test_metrics.py -v` — Expected: 5 passed

- [ ] **Step 5: 커밋**

```powershell
git add simcore\metrics.py tests\test_metrics.py
git commit -m "feat: 성과 지표 (TWR/MDD/누적손익)"
```

---

### Task 8: engine.py (1부) — 신호 소비·주문 예약·시가 체결

**Files:**
- Create: `simcore/engine.py`
- Test: `tests/test_engine_orders.py`

**Interfaces:**
- Consumes: `Portfolio`, `SymbolSnapshot`, `Config`, `costs`
- Produces:
  - `CharacterSpec(name, markets: tuple[Market, ...], base_currency: Currency)` frozen dataclass
  - `DEFAULT_CHARACTERS: tuple[CharacterSpec, ...]` — 국내형(KR/KRW), 해외형(US/USD), 범용형(KR+US/KRW)
  - `Engine(config, characters=DEFAULT_CHARACTERS)`
    - `.states: dict[str, CharacterState]` (CharacterState: `.spec`, `.portfolio`, `.pending_buys`, `.pending_sells`, `.cooldowns: dict[str, int]`)
    - `.start(d, fx_rate)` — 캐릭터별 초기자금 입금
    - `.evaluate_close(d, market, snaps: dict[str, SymbolSnapshot])` — 매도 판정(적신호 카운트 + R7/R10 종가 기준 추가) → `pending_sells`, 매수 후보(청신호 ≥ 임계값, 쿨다운/보유 제외) → `pending_buys`. 쿨다운은 해당 시장 마감마다 1 감소
    - `.fill_open(d, market, opens: dict[str, float], fx_rate)` — 매도 먼저(현금 확보), 매수는 우선순위 정렬(신호 수 → 등락률 → 거래량) 후 `가용현금 ÷ 남은슬롯` 예산으로 정수 주 체결. 범용형의 미국 매수는 필요분만 환전, 매도 대금은 즉시 원화 환전. 체결 못 한 매수 주문은 당일 소멸, 매도 주문(거래정지 등 가격 없음)은 이월
- 내부 헬퍼 `._sell(st, d, symbol, price, reason, fx_rate, red_count=0, fired=())` — 매도 + 쿨다운 설정 + 범용형 환전 (Task 9 도 사용)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_engine_orders.py`

```python
from datetime import date
from dataclasses import replace
import pytest
from simcore.config import Config
from simcore.models import Market, Currency, SymbolSnapshot, Side, TradeReason
from simcore.engine import Engine, CharacterSpec

D1, D2, D3, D4 = (date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8), date(2025, 1, 9))
KR_ONLY = (CharacterSpec("국내형", (Market.KR,), Currency.KRW),)

def snap(sym, green=(), red=(), close=100.0, chg=0.0, vol=1000.0, market=Market.KR):
    return SymbolSnapshot(sym, market, tuple(green), tuple(red), close, chg, vol)

def make_engine(buy_threshold=3, max_positions=5):
    cfg = Config()
    cfg = replace(cfg, rules=replace(cfg.rules, buy_threshold=buy_threshold,
                                     max_positions=max_positions))
    e = Engine(cfg, characters=KR_ONLY)
    e.start(D1, fx_rate=1300.0)
    return e

def test_buy_when_green_meets_threshold():
    e = make_engine(buy_threshold=3)
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1", "G2", "G4"))})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    st = e.states["국내형"]
    assert "A" in st.portfolio.positions
    t = st.portfolio.trades[-1]
    assert t.side == Side.BUY and t.reason == TradeReason.SIGNAL_BUY and t.green_count == 3

def test_no_buy_below_threshold():
    e = make_engine(buy_threshold=3)
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1", "G2"))})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    assert e.states["국내형"].portfolio.positions == {}

def test_priority_more_greens_first_when_slots_limited():
    e = make_engine(buy_threshold=2, max_positions=1)
    snaps = {
        "A": snap("A", green=("G1", "G2")),
        "B": snap("B", green=("G1", "G2", "G4")),  # 신호 더 많음 → 우선
    }
    e.evaluate_close(D1, Market.KR, snaps)
    e.fill_open(D2, Market.KR, {"A": 100.0, "B": 100.0}, fx_rate=1300.0)
    pos = e.states["국내형"].portfolio.positions
    assert list(pos) == ["B"]

def test_sizing_splits_cash_by_remaining_slots():
    e = make_engine(buy_threshold=1, max_positions=5)
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1",))})
    e.fill_open(D2, Market.KR, {"A": 10000.0}, fx_rate=1300.0)
    qty = e.states["국내형"].portfolio.positions["A"].quantity
    # 예산 = 1억/5 = 2000만 → 수수료 감안 정수 주
    assert qty == int((100_000_000 / 5) // (10000.0 * 1.00015))

def test_sell_when_red_meets_threshold():
    e = make_engine(buy_threshold=1)
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1",))})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    e.evaluate_close(D2, Market.KR, {"A": snap("A", red=("R1", "R2", "R4"))})
    e.fill_open(D3, Market.KR, {"A": 95.0}, fx_rate=1300.0)
    st = e.states["국내형"]
    assert "A" not in st.portfolio.positions
    t = st.portfolio.trades[-1]
    assert t.reason == TradeReason.SIGNAL_SELL and t.red_count == 3

def test_red_signals_ignored_for_unheld_symbol():
    e = make_engine()
    e.evaluate_close(D1, Market.KR, {"A": snap("A", red=("R1", "R2", "R4", "R5"))})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    assert e.states["국내형"].portfolio.trades[:] == []  # 롱 온리: 미보유 적신호 무시

def test_cooldown_blocks_rebuy_for_two_sessions():
    e = make_engine(buy_threshold=1)
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1",))})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    e.evaluate_close(D2, Market.KR, {"A": snap("A", red=("R1", "R2", "R4"))})
    e.fill_open(D3, Market.KR, {"A": 100.0}, fx_rate=1300.0)   # 매도 체결
    # 매도 당일(D3) 마감: 쿨다운 2→1, 매수 후보 제외
    e.evaluate_close(D3, Market.KR, {"A": snap("A", green=("G1",))})
    e.fill_open(D4, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    assert "A" not in e.states["국내형"].portfolio.positions
    # 다음 마감: 쿨다운 1→0, 이제 후보 가능
    e.evaluate_close(D4, Market.KR, {"A": snap("A", green=("G1",))})
    e.fill_open(date(2025, 1, 10), Market.KR, {"A": 100.0}, fx_rate=1300.0)
    assert "A" in e.states["국내형"].portfolio.positions

def test_r7_close_based_counts_toward_sell_threshold():
    e = make_engine(buy_threshold=1)
    e.evaluate_close(D1, Market.KR, {"A": snap("A", green=("G1",))})
    e.fill_open(D2, Market.KR, {"A": 100.0}, fx_rate=1300.0)
    # 종가 92 = 평단 100 대비 -8% → R7 추가, R1·R2 와 합쳐 3개 도달
    e.evaluate_close(D2, Market.KR, {"A": snap("A", red=("R1", "R2"), close=92.0)})
    st = e.states["국내형"]
    assert len(st.pending_sells) == 1 and "R7" in st.pending_sells[0].fired
```

- [ ] **Step 2: 실패 확인** — Run: `.venv\Scripts\python -m pytest tests\test_engine_orders.py -v` — Expected: FAIL

- [ ] **Step 3: 구현** — `simcore/engine.py`

```python
"""매매 엔진. 신호 결과(SymbolSnapshot)를 소비해 7/3 규칙·손익절·포지션 관리를 수행한다.
시계·데이터 소스를 모른다 — 리플레이와 라이브가 같은 메서드를 호출한다."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date as Date

from simcore.config import Config
from simcore import costs as costmod
from simcore.models import (
    Currency, DailyBar, Market, MARKET_CURRENCY, SymbolSnapshot, TradeReason,
)
from simcore.portfolio import Portfolio


@dataclass(frozen=True)
class CharacterSpec:
    name: str
    markets: tuple[Market, ...]
    base_currency: Currency


DEFAULT_CHARACTERS: tuple[CharacterSpec, ...] = (
    CharacterSpec("국내형", (Market.KR,), Currency.KRW),
    CharacterSpec("해외형", (Market.US,), Currency.USD),
    CharacterSpec("범용형", (Market.KR, Market.US), Currency.KRW),
)


@dataclass
class PendingBuy:
    symbol: str
    market: Market
    green_count: int
    fired: tuple[str, ...]
    change_pct: float
    volume: float


@dataclass
class PendingSell:
    symbol: str
    market: Market
    reason: TradeReason
    red_count: int
    fired: tuple[str, ...]


@dataclass
class CharacterState:
    spec: CharacterSpec
    portfolio: Portfolio
    pending_buys: list[PendingBuy] = field(default_factory=list)
    pending_sells: list[PendingSell] = field(default_factory=list)
    cooldowns: dict[str, int] = field(default_factory=dict)


class Engine:
    def __init__(self, config: Config,
                 characters: tuple[CharacterSpec, ...] = DEFAULT_CHARACTERS):
        self.config = config
        self.states: dict[str, CharacterState] = {
            s.name: CharacterState(s, Portfolio(s.name, s.base_currency, config))
            for s in characters
        }

    def start(self, d: Date, fx_rate: float) -> None:
        for st in self.states.values():
            st.portfolio.deposit(d, self.config.initial_capital_krw, fx_rate)

    # ---- 장 마감: 신호 판정 → 다음 개장 주문 예약 ----
    def evaluate_close(self, d: Date, market: Market,
                       snaps: dict[str, SymbolSnapshot]) -> None:
        r = self.config.rules
        for st in self.states.values():
            if market not in st.spec.markets:
                continue
            # 쿨다운: 이 시장 마감마다 1 감소 (이 시장 종목만)
            for sym in list(st.cooldowns):
                if sym in snaps:
                    st.cooldowns[sym] -= 1
                    if st.cooldowns[sym] <= 0:
                        del st.cooldowns[sym]
            # 보유 종목 매도 판정 (R7/R10 은 종가 기준으로 여기서 추가)
            already_pending = {ps.symbol for ps in st.pending_sells}
            for sym, pos in st.portfolio.positions.items():
                if pos.market != market or sym not in snaps or sym in already_pending:
                    continue
                s = snaps[sym]
                red = list(s.red)
                if s.close <= pos.avg_price * (1 + r.stop_loss_pct):
                    red.append("R7")
                if s.close >= pos.avg_price * (1 + r.take_profit_pct):
                    red.append("R10")
                if len(red) >= r.sell_threshold:
                    st.pending_sells.append(PendingSell(
                        sym, market, TradeReason.SIGNAL_SELL, len(red), tuple(red)))
            # 매수 후보 (미보유 · 쿨다운 아님 · 임계값 이상)
            held = set(st.portfolio.positions) | {b.symbol for b in st.pending_buys}
            for sym, s in snaps.items():
                if (sym in held or st.cooldowns.get(sym, 0) > 0
                        or len(s.green) < r.buy_threshold):
                    continue
                st.pending_buys.append(PendingBuy(
                    sym, market, len(s.green), s.green, s.change_pct, s.volume))

    # ---- 개장: 예약 주문 체결 ----
    def fill_open(self, d: Date, market: Market, opens: dict[str, float],
                  fx_rate: float) -> None:
        r = self.config.rules
        for st in self.states.values():
            if market not in st.spec.markets:
                continue
            # 1) 매도 먼저 (현금 확보). 가격 없는(거래정지) 매도는 이월
            carried: list[PendingSell] = []
            for ps in st.pending_sells:
                if ps.market != market:
                    carried.append(ps)
                    continue
                if ps.symbol not in st.portfolio.positions:
                    continue  # 이미 손절 등으로 청산됨 → 폐기
                price = opens.get(ps.symbol)
                if price is None:
                    carried.append(ps)
                    continue
                self._sell(st, d, ps.symbol, price, ps.reason, fx_rate,
                           red_count=ps.red_count, fired=ps.fired)
            st.pending_sells = carried
            # 2) 매수: 우선순위 = 신호 수 → 등락률 → 거래량
            buys = sorted((b for b in st.pending_buys if b.market == market),
                          key=lambda b: (-b.green_count, -b.change_pct, -b.volume))
            st.pending_buys = [b for b in st.pending_buys if b.market != market]
            for b in buys:
                slots = r.max_positions - len(st.portfolio.positions)
                if slots <= 0:
                    break
                price = opens.get(b.symbol)
                if (price is None or b.symbol in st.portfolio.positions
                        or st.cooldowns.get(b.symbol, 0) > 0):
                    continue
                self._buy(st, d, b, price, fx_rate, slots)

    def _buy(self, st: CharacterState, d: Date, b: PendingBuy, price: float,
             fx_rate: float, slots: int) -> None:
        c = self.config.costs
        cur = MARKET_CURRENCY[b.market]
        pf = st.portfolio
        cross_currency = (st.spec.base_currency == Currency.KRW and cur == Currency.USD)
        if cross_currency:
            budget = costmod.krw_to_usd(pf.cash[Currency.KRW] / slots, fx_rate, c.fx_fee)
        else:
            budget = pf.cash[cur] / slots
        fee_rate = costmod.commission_rate(b.market, c)
        fill_price = price * (1 + c.slippage)
        qty = int(budget // (fill_price * (1 + fee_rate)))
        if qty <= 0:
            return
        if cross_currency:
            pf.convert_to_usd(qty * fill_price * (1 + fee_rate), fx_rate)
        pf.buy(d, b.symbol, b.market, qty, fill_price, TradeReason.SIGNAL_BUY,
               green_count=b.green_count, fired=b.fired)

    def _sell(self, st: CharacterState, d: Date, symbol: str, price: float,
              reason: TradeReason, fx_rate: float, red_count: int = 0,
              fired: tuple[str, ...] = ()) -> None:
        pos = st.portfolio.positions[symbol]
        fill_price = price * (1 - self.config.costs.slippage)
        st.portfolio.sell(d, symbol, fill_price, reason,
                          red_count=red_count, fired=fired)
        st.cooldowns[symbol] = self.config.rules.cooldown_days
        if st.spec.base_currency == Currency.KRW and pos.market == Market.US:
            st.portfolio.convert_all_usd_to_krw(fx_rate)  # 범용형: 매도 대금 즉시 원화로
```

- [ ] **Step 4: 통과 확인** — Run: `.venv\Scripts\python -m pytest tests\test_engine_orders.py -v` — Expected: 8 passed

- [ ] **Step 5: 커밋**

```powershell
git add simcore\engine.py tests\test_engine_orders.py
git commit -m "feat: 엔진 1부 — 신호 소비, 주문 예약, 시가 체결, 사이징/우선순위/쿨다운"
```

---

### Task 9: engine.py (2부) — 손절/익절·입출금·자산 스냅샷

**Files:**
- Modify: `simcore/engine.py` (메서드 추가)
- Test: `tests/test_engine_risk.py`

**Interfaces:**
- Consumes: Task 8 의 `Engine`, `_sell`
- Produces (Engine 메서드 추가):
  - `.check_stops(d, market, bars: dict[str, DailyBar], fx_rate)` — 보유 종목의 당일 저가/고가로 손절(-7%)/익절(+15%) 판정, **손절 우선**, 트리거 가격으로 체결. 라이브 모드는 현재가를 `low=high=현재가` 인 DailyBar 로 감싸 같은 메서드 사용
  - `.apply_flow(d, character, amount_krw, fx_rate, open_prices=None, liquidate=()) -> None` — 입금은 즉시. 출금은 `liquidate` 에 지정된 보유 종목을 당일 시가로 먼저 매도(`USER_WITHDRAWAL`, 쿨다운 적용) 후 출금. 그래도 부족하면 `InsufficientCashError` 전파
  - `.snapshot(last_close: dict[str, float], fx_rate) -> dict[str, float]` — 캐릭터별 총자산(KRW)
  - `.force_close(d, symbol, price, fx_rate)` — 상장폐지 처리: 보유 캐릭터 전부 `DELISTED` 사유로 청산

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_engine_risk.py`

```python
from datetime import date
from dataclasses import replace
import pytest
from simcore.config import Config
from simcore.models import Market, Currency, DailyBar, SymbolSnapshot, TradeReason
from simcore.engine import Engine, CharacterSpec
from simcore.portfolio import InsufficientCashError

D1, D2, D3 = date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)
KR_ONLY = (CharacterSpec("국내형", (Market.KR,), Currency.KRW),)

def bar(sym, low, high, d=D3, close=None):
    c = close if close is not None else (low + high) / 2
    return DailyBar(sym, d, c, high, low, c, 1000.0)

def engine_with_position(price=100.0):
    cfg = replace(Config(), rules=replace(Config().rules, buy_threshold=1))
    e = Engine(cfg, characters=KR_ONLY)
    e.start(D1, fx_rate=1300.0)
    e.evaluate_close(D1, Market.KR, {"A": SymbolSnapshot(
        "A", Market.KR, ("G1",), (), price, 0.0, 1000.0)})
    e.fill_open(D2, Market.KR, {"A": price}, fx_rate=1300.0)
    return e

def test_stop_loss_triggers_at_low():
    e = engine_with_position(100.0)
    e.check_stops(D3, Market.KR, {"A": bar("A", low=90.0, high=95.0)}, fx_rate=1300.0)
    t = e.states["국내형"].portfolio.trades[-1]
    assert t.reason == TradeReason.STOP_LOSS
    assert t.price == pytest.approx(93.0)  # 평단 100 × (1-7%)

def test_take_profit_triggers_at_high():
    e = engine_with_position(100.0)
    e.check_stops(D3, Market.KR, {"A": bar("A", low=110.0, high=120.0)}, fx_rate=1300.0)
    t = e.states["국내형"].portfolio.trades[-1]
    assert t.reason == TradeReason.TAKE_PROFIT
    assert t.price == pytest.approx(115.0)

def test_stop_beats_take_when_both_hit_same_day():
    e = engine_with_position(100.0)
    e.check_stops(D3, Market.KR, {"A": bar("A", low=90.0, high=120.0)}, fx_rate=1300.0)
    assert e.states["국내형"].portfolio.trades[-1].reason == TradeReason.STOP_LOSS

def test_deposit_flow():
    e = engine_with_position()
    before = e.states["국내형"].portfolio.cash[Currency.KRW]
    e.apply_flow(D3, "국내형", 50_000_000, fx_rate=1300.0)
    assert e.states["국내형"].portfolio.cash[Currency.KRW] == pytest.approx(before + 50_000_000)

def test_withdrawal_with_user_selected_liquidation():
    e = engine_with_position(100.0)
    st = e.states["국내형"]
    cash = st.portfolio.cash[Currency.KRW]
    # 현금보다 큰 출금 → 청산 지정 없으면 에러
    with pytest.raises(InsufficientCashError):
        e.apply_flow(D3, "국내형", -(cash + 1_000_000), fx_rate=1300.0)
    # 사용자가 A 청산을 지정하면 성공
    e.apply_flow(D3, "국내형", -(cash + 1_000_000), fx_rate=1300.0,
                 open_prices={"A": 100.0}, liquidate=("A",))
    assert "A" not in st.portfolio.positions
    t = [t for t in st.portfolio.trades if t.reason == TradeReason.USER_WITHDRAWAL]
    assert len(t) == 1
    assert st.cooldowns.get("A", 0) > 0  # 출금 청산도 쿨다운 적용

def test_snapshot_reports_equity_per_character():
    e = engine_with_position(100.0)
    eq = e.snapshot({"A": 110.0}, fx_rate=1300.0)
    assert eq["국내형"] > 100_000_000  # 10% 평가이익 반영
```

- [ ] **Step 2: 실패 확인** — Run: `.venv\Scripts\python -m pytest tests\test_engine_risk.py -v` — Expected: FAIL

- [ ] **Step 3: 구현** — `simcore/engine.py` 에 메서드 추가 (Engine 클래스 안)

```python
    # ---- 장중: 손절/익절 (리플레이 = 당일 OHLC 근사, 라이브 = 현재가 bar) ----
    def check_stops(self, d: Date, market: Market, bars: dict[str, DailyBar],
                    fx_rate: float) -> None:
        r = self.config.rules
        for st in self.states.values():
            if market not in st.spec.markets:
                continue
            for sym in list(st.portfolio.positions):
                pos = st.portfolio.positions[sym]
                if pos.market != market or sym not in bars:
                    continue
                b = bars[sym]
                stop_px = pos.avg_price * (1 + r.stop_loss_pct)
                take_px = pos.avg_price * (1 + r.take_profit_pct)
                if b.low <= stop_px:  # 손절 우선 (보수적)
                    self._sell(st, d, sym, stop_px, TradeReason.STOP_LOSS, fx_rate)
                elif b.high >= take_px:
                    self._sell(st, d, sym, take_px, TradeReason.TAKE_PROFIT, fx_rate)

    # ---- 사용자 입출금 ----
    def apply_flow(self, d: Date, character: str, amount_krw: float, fx_rate: float,
                   open_prices: dict[str, float] | None = None,
                   liquidate: tuple[str, ...] = ()) -> None:
        st = self.states[character]
        if amount_krw >= 0:
            st.portfolio.deposit(d, amount_krw, fx_rate)
            return
        for sym in liquidate:  # 사용자가 지정한 청산 종목을 당일 시가로 매도
            if sym not in st.portfolio.positions:
                continue
            price = (open_prices or {}).get(sym)
            if price is None:
                raise ValueError(f"{character}: {sym} 청산 가격이 없습니다")
            self._sell(st, d, sym, price, TradeReason.USER_WITHDRAWAL, fx_rate)
        st.portfolio.withdraw(d, -amount_krw, fx_rate)

    # ---- 평가·강제 처리 ----
    def snapshot(self, last_close: dict[str, float], fx_rate: float) -> dict[str, float]:
        return {name: st.portfolio.equity_krw(last_close, fx_rate)
                for name, st in self.states.items()}

    def force_close(self, d: Date, symbol: str, price: float, fx_rate: float) -> None:
        """상장폐지 등: 모든 캐릭터에서 마지막 가격으로 강제 청산."""
        for st in self.states.values():
            if symbol in st.portfolio.positions:
                self._sell(st, d, symbol, price, TradeReason.DELISTED, fx_rate)
```

- [ ] **Step 4: 통과 확인** — Run: `.venv\Scripts\python -m pytest tests\test_engine_risk.py -v` — Expected: 7 passed. 이어서 `.venv\Scripts\python -m pytest -q` 전체 통과 확인.

- [ ] **Step 5: 커밋**

```powershell
git add simcore\engine.py tests\test_engine_risk.py
git commit -m "feat: 엔진 2부 — 손절/익절(손절 우선), 사용자 입출금, 자산 스냅샷, 강제청산"
```

---

### Task 10: data.py + universe.py — 과거 데이터 로딩·캐시

**Files:**
- Create: `simcore/data.py`, `simcore/universe.py`
- Test: `tests/test_data.py`

**Interfaces:**
- Produces:
  - `data.load_kr_daily(symbols, start, end, cache_dir) -> dict[str, pd.DataFrame]` — pykrx. 컬럼 `open/high/low/close/volume`, DatetimeIndex 오름차순
  - `data.load_us_daily(symbols, start, end, cache_dir) -> dict[str, pd.DataFrame]` — yfinance, 동일 스키마
  - `data.load_fx(start, end, cache_dir) -> pd.Series` — KRW/USD 일별 종가, ffill
  - `data.LOOKBACK_PAD_DAYS = 120` — 지표 워밍업용으로 start 이전을 추가로 받는 달력일수
  - `universe.kospi200(cache_dir, base_date) -> list[str]` — pykrx 지수 구성종목
  - `universe.sp500(cache_dir) -> list[str]` — Wikipedia → 실패 시 `FALLBACK_SP500`(대형주 30개 내장 리스트)
  - 캐시: `cache_dir/{market}_{symbol}_{start}_{end}.parquet` 정확 일치 키. 네트워크 함수는 `fetch_fn` 파라미터로 주입 가능(테스트용)

- [ ] **Step 1: 실패하는 테스트 작성 (네트워크 불필요 — fetch 주입)** — `tests/test_data.py`

```python
import numpy as np
import pandas as pd
from simcore.data import _cached, load_fx

def fake_fetch():
    idx = pd.bdate_range("2025-01-02", periods=10)
    return pd.DataFrame({
        "open": np.full(10, 100.0), "high": np.full(10, 101.0),
        "low": np.full(10, 99.0), "close": np.full(10, 100.5),
        "volume": np.full(10, 1000.0),
    }, index=idx)

def test_cache_write_then_read(tmp_path):
    calls = []
    def fetch():
        calls.append(1)
        return fake_fetch()
    df1 = _cached(tmp_path, "KR_005930_20250102_20250115", fetch)
    df2 = _cached(tmp_path, "KR_005930_20250102_20250115", fetch)
    assert len(calls) == 1              # 두 번째는 캐시 히트
    pd.testing.assert_frame_equal(df1, df2)

def test_cache_returns_copy_schema():
    # 캐시 파일이 index 를 보존하는지
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        df = _cached(pathlib.Path(td), "k", fake_fetch)
        assert isinstance(df.index, pd.DatetimeIndex)
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
```

- [ ] **Step 2: 실패 확인** — Run: `.venv\Scripts\python -m pytest tests\test_data.py -v` — Expected: FAIL

- [ ] **Step 3: 구현** — `simcore/data.py`

```python
"""과거 시세 로딩 + parquet 캐시. 네트워크 실패 시 캐시 우선, 캐시도 없으면 명확한 에러."""
from __future__ import annotations
from datetime import date as Date, timedelta
from pathlib import Path
from typing import Callable
import pandas as pd

LOOKBACK_PAD_DAYS = 120  # 지표 워밍업(최소 61거래일)을 위한 달력일 여유
COLS = ["open", "high", "low", "close", "volume"]


def _cached(cache_dir: Path, key: str, fetch: Callable[[], pd.DataFrame]) -> pd.DataFrame:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{key}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    df = fetch()
    df.to_parquet(path)
    return df


def _key(market: str, symbol: str, start: Date, end: Date) -> str:
    return f"{market}_{symbol}_{start:%Y%m%d}_{end:%Y%m%d}"


def load_kr_daily(symbols: list[str], start: Date, end: Date,
                  cache_dir: Path) -> dict[str, pd.DataFrame]:
    from pykrx import stock
    pad_start = start - timedelta(days=LOOKBACK_PAD_DAYS)
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        def fetch(sym=sym):
            raw = stock.get_market_ohlcv(f"{pad_start:%Y%m%d}", f"{end:%Y%m%d}", sym)
            raw = raw.rename(columns={"시가": "open", "고가": "high", "저가": "low",
                                      "종가": "close", "거래량": "volume"})
            raw.index = pd.to_datetime(raw.index)
            return raw[COLS].astype(float).sort_index()
        try:
            df = _cached(cache_dir, _key("KR", sym, pad_start, end), fetch)
            if not df.empty:
                out[sym] = df
        except Exception as exc:  # 개별 종목 실패는 건너뛰고 경고
            print(f"[data] KR {sym} 로딩 실패: {exc}")
    if not out:
        raise RuntimeError("국내 시세를 하나도 로딩하지 못했습니다 (네트워크/캐시 확인)")
    return out


def load_us_daily(symbols: list[str], start: Date, end: Date,
                  cache_dir: Path) -> dict[str, pd.DataFrame]:
    import yfinance as yf
    pad_start = start - timedelta(days=LOOKBACK_PAD_DAYS)
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        def fetch(sym=sym):
            raw = yf.download(sym, start=pad_start, end=end + timedelta(days=1),
                              auto_adjust=True, progress=False)
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            raw = raw.rename(columns=str.lower)[COLS]
            raw.index = pd.to_datetime(raw.index).tz_localize(None)
            return raw.astype(float).sort_index()
        try:
            df = _cached(cache_dir, _key("US", sym, pad_start, end), fetch)
            if not df.empty:
                out[sym] = df
        except Exception as exc:
            print(f"[data] US {sym} 로딩 실패: {exc}")
    if not out:
        raise RuntimeError("미국 시세를 하나도 로딩하지 못했습니다 (네트워크/캐시 확인)")
    return out


def load_fx(start: Date, end: Date, cache_dir: Path) -> pd.Series:
    """KRW per USD 일별 종가."""
    import yfinance as yf
    pad_start = start - timedelta(days=LOOKBACK_PAD_DAYS)

    def fetch():
        raw = yf.download("KRW=X", start=pad_start, end=end + timedelta(days=1),
                          auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        s = raw["Close"] if "Close" in raw.columns else raw["close"]
        s.index = pd.to_datetime(s.index).tz_localize(None)
        return s.rename("fx").to_frame()

    df = _cached(cache_dir, _key("FX", "KRWUSD", pad_start, end), fetch)
    return df["fx"].ffill()
```

그리고 `simcore/universe.py`:

```python
"""거래 유니버스. 국내 = 코스피200(pykrx), 미국 = S&P500(Wikipedia, 실패 시 내장 목록)."""
from __future__ import annotations
from datetime import date as Date
from pathlib import Path
import pandas as pd

FALLBACK_SP500 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "LLY", "AVGO", "JPM",
    "TSLA", "XOM", "UNH", "V", "PG", "MA", "COST", "JNJ", "HD", "WMT",
    "NFLX", "ABBV", "CRM", "BAC", "ORCL", "CVX", "MRK", "KO", "AMD", "PEP",
]


def kospi200(cache_dir: Path, base_date: Date) -> list[str]:
    path = Path(cache_dir) / f"universe_kospi200_{base_date:%Y%m%d}.csv"
    if path.exists():
        return pd.read_csv(path, dtype=str)["symbol"].tolist()
    from pykrx import stock
    syms = stock.get_index_portfolio_deposit_file("1028", f"{base_date:%Y%m%d}")
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"symbol": syms}).to_csv(path, index=False)
    return list(syms)


def sp500(cache_dir: Path) -> list[str]:
    path = Path(cache_dir) / "universe_sp500.csv"
    if path.exists():
        return pd.read_csv(path, dtype=str)["symbol"].tolist()
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        syms = [s.replace(".", "-") for s in tables[0]["Symbol"].tolist()]
    except Exception:
        syms = list(FALLBACK_SP500)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"symbol": syms}).to_csv(path, index=False)
    return syms
```

- [ ] **Step 4: 통과 확인** — Run: `.venv\Scripts\python -m pytest tests\test_data.py -v` — Expected: 2 passed

- [ ] **Step 5: 커밋**

```powershell
git add simcore\data.py simcore\universe.py tests\test_data.py
git commit -m "feat: 과거 데이터 로딩(pykrx/yfinance/환율) + parquet 캐시 + 유니버스"
```

---

### Task 11: replay.py + report.py — 리플레이 오케스트레이션·CLI·통합 테스트

**Files:**
- Create: `simcore/replay.py`, `simcore/report.py`, `simcore/__main__.py`
- Test: `tests/test_replay_integration.py`

**Interfaces:**
- Consumes: Engine, signals, metrics, data, universe
- Produces:
  - `DataBundle(kr: dict[str, pd.DataFrame], us: dict[str, pd.DataFrame], fx: pd.Series)` — 테스트는 합성 번들을 직접 만들고, CLI 는 data.py 로 채운다
  - `FlowEvent(date, character, amount_krw, liquidate: tuple[str, ...])`
  - `run_replay(config, bundle, start, end, flows: list[FlowEvent] = ()) -> ReplayResult`
  - `ReplayResult(trades: pd.DataFrame, equity: pd.DataFrame(index=날짜, columns=캐릭터), flows_by_char: dict[str, pd.Series], green_hist: pd.Series, summary: dict)` — summary: 캐릭터별 `{twr, mdd, pnl_krw, n_trades}` + 벤치마크
  - CLI: `python -m simcore --start 2025-01-01 --end 2025-12-31 [--flows flows.csv] [--buy-threshold N] [--kr-top N] [--us-top N] [--out out] [--cache data/cache]`
  - `report.write_outputs(result, config, out_dir)` — `trades.csv`, `equity_curve.csv`, `signal_distribution.csv`, 콘솔 요약표, `docs/experiments/replay_{start}_{end}_{seq}.md` (설정 스냅샷 + 요약)

- [ ] **Step 1: 실패하는 통합 테스트 작성** — `tests/test_replay_integration.py`

합성 데이터로 결정론적 시나리오를 검증한다. `buy_threshold=3` 으로 낮춰(설정 주입) 기술 신호만으로 매수가 발생하게 한다.

```python
from datetime import date
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from simcore.config import Config
from simcore.replay import DataBundle, FlowEvent, run_replay

def make_ohlcv(closes, idx):
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({
        "open": c.shift(1).fillna(c.iloc[0]),
        "high": c * 1.005, "low": c * 0.995,
        "close": c, "volume": np.full(len(c), 10_000.0),
    }, index=idx)

def make_bundle():
    idx = pd.bdate_range("2024-10-01", periods=160)
    # UPUP: 120일 상승 후 하루 -20% 폭락 → 매수 후 손절 시나리오
    # (-20%: 상승 중 익절/재매수로 평단이 갱신되어도 확실히 -7% 손절선을 뚫는 크기)
    closes = list(100 * (1.005 ** np.arange(120)))
    crash = closes[-1] * 0.80
    closes += [crash] * 40
    kr = {"UPUP": make_ohlcv(closes, idx)}
    fx = pd.Series(1300.0, index=idx)
    return DataBundle(kr=kr, us={}, fx=fx), idx

CFG = replace(Config(), rules=replace(Config().rules, buy_threshold=3))

def test_buys_then_stops_out_deterministically():
    bundle, idx = make_bundle()
    r1 = run_replay(CFG, bundle, idx[70].date(), idx[-1].date())
    r2 = run_replay(CFG, bundle, idx[70].date(), idx[-1].date())
    trades = r1.trades[r1.trades.character == "국내형"]
    assert (trades.side == "BUY").sum() >= 1
    assert "STOP_LOSS" in set(trades.reason)
    pd.testing.assert_frame_equal(r1.trades, r2.trades)  # 결정론

def test_equity_curve_continuous_and_invariant():
    bundle, idx = make_bundle()
    r = run_replay(CFG, bundle, idx[70].date(), idx[-1].date())
    eq = r.equity["국내형"]
    assert eq.notna().all()
    assert (eq > 0).all()

def test_withdrawal_flow_with_liquidation():
    bundle, idx = make_bundle()
    # 매수 체결(약 62번째 세션 이후)이 확실히 끝난 날짜에 거액 출금 + UPUP 청산 지정
    wd_date = idx[115].date()
    flows = [FlowEvent(wd_date, "국내형", -95_000_000, ("UPUP",))]
    r = run_replay(CFG, bundle, idx[70].date(), idx[-1].date(), flows=flows)
    tr = r.trades[(r.trades.character == "국내형") & (r.trades.reason == "USER_WITHDRAWAL")]
    assert len(tr) == 1
    assert r.flows_by_char["국내형"].sum() == pytest.approx(-95_000_000)
```

- [ ] **Step 2: 실패 확인** — Run: `.venv\Scripts\python -m pytest tests\test_replay_integration.py -v` — Expected: FAIL

- [ ] **Step 3: 구현** — `simcore/replay.py`

```python
"""리플레이 오케스트레이션: 과거 일봉을 날짜 루프로 엔진에 주입한다.
같은 달력 날짜의 KR·US 세션은 같은 스텝에서 처리한다(일 단위 근사)."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date as Date
import pandas as pd

from simcore.config import Config
from simcore.engine import Engine
from simcore.models import DailyBar, Market, SymbolSnapshot
from simcore import signals as sigmod
from simcore import metrics


@dataclass
class DataBundle:
    kr: dict[str, pd.DataFrame]
    us: dict[str, pd.DataFrame]
    fx: pd.Series  # KRW per USD


@dataclass(frozen=True)
class FlowEvent:
    date: Date
    character: str
    amount_krw: float
    liquidate: tuple[str, ...] = ()


@dataclass
class ReplayResult:
    trades: pd.DataFrame
    equity: pd.DataFrame
    flows_by_char: dict[str, pd.Series]
    green_hist: pd.Series
    summary: dict


def _market_data(bundle: DataBundle) -> dict[Market, dict[str, pd.DataFrame]]:
    return {Market.KR: bundle.kr, Market.US: bundle.us}


def run_replay(config: Config, bundle: DataBundle, start: Date, end: Date,
               flows: list[FlowEvent] = ()) -> ReplayResult:
    md = _market_data(bundle)
    # 1) 신호 표를 종목당 한 번 벡터화 계산
    frames = {m: {sym: sigmod.evaluate_frame(df, config.signals)
                  for sym, df in data.items()}
              for m, data in md.items()}
    # 2) 시뮬 날짜 = 두 시장 거래일 합집합 (start~end)
    all_dates = sorted({d for data in md.values() for df in data.values()
                        for d in df.index if start <= d.date() <= end})
    if not all_dates:
        raise ValueError("리플레이 구간에 거래일이 없습니다")
    flow_map: dict[Date, list[FlowEvent]] = {}
    for f in flows:
        flow_map.setdefault(f.date, []).append(f)

    engine = Engine(config)
    fx0 = float(bundle.fx.asof(all_dates[0]))
    engine.start(all_dates[0].date(), fx0)

    last_close: dict[str, float] = {}
    equity_rows, green_counts = [], []
    for ts in all_dates:
        d = ts.date()
        fx = float(bundle.fx.asof(ts))
        opens_today: dict[str, float] = {}
        for market, data in md.items():
            opens = {sym: float(df.loc[ts, "open"])
                     for sym, df in data.items() if ts in df.index}
            opens_today.update(opens)
            if not opens:
                continue
            # (a) 입출금은 첫 시장 개장 전 1회 처리 (아래 공통 블록에서)
        for f in flow_map.get(d, []):
            engine.apply_flow(d, f.character, f.amount_krw, fx,
                              open_prices=opens_today, liquidate=f.liquidate)
        for market, data in md.items():
            todays = {sym: df for sym, df in data.items() if ts in df.index}
            if not todays:
                continue
            opens = {sym: float(df.loc[ts, "open"]) for sym, df in todays.items()}
            engine.fill_open(d, market, opens, fx)
            bars = {sym: DailyBar(sym, d, float(df.loc[ts, "open"]),
                                  float(df.loc[ts, "high"]), float(df.loc[ts, "low"]),
                                  float(df.loc[ts, "close"]), float(df.loc[ts, "volume"]))
                    for sym, df in todays.items()}
            engine.check_stops(d, market, bars, fx)
            snaps: dict[str, SymbolSnapshot] = {}
            for sym, df in todays.items():
                green, red = sigmod.fired_at(frames[market][sym], ts)
                loc = df.index.get_loc(ts)
                prev_close = float(df["close"].iloc[loc - 1]) if loc > 0 else float(df.loc[ts, "close"])
                close = float(df.loc[ts, "close"])
                snaps[sym] = SymbolSnapshot(
                    sym, market, green, red, close,
                    close / prev_close - 1.0, float(df.loc[ts, "volume"]))
                last_close[sym] = close
                green_counts.append(len(green))
            engine.evaluate_close(d, market, snaps)
        eq = engine.snapshot(last_close, fx)
        equity_rows.append({"date": ts, **eq})

    # ---- 결과 집계 ----
    equity = pd.DataFrame(equity_rows).set_index("date")
    trades = pd.DataFrame([{
        "date": t.date, "character": t.character, "symbol": t.symbol,
        "market": t.market.value, "side": t.side.value, "quantity": t.quantity,
        "price": t.price, "fee": t.fee, "tax": t.tax, "reason": t.reason.value,
        "green_count": t.green_count, "red_count": t.red_count,
        "fired": ";".join(t.fired), "realized_pnl": t.realized_pnl,
    } for st in engine.states.values() for t in st.portfolio.trades])

    flows_by_char, summary = {}, {}
    for name, st in engine.states.items():
        f = pd.Series({pd.Timestamp(fl.date): fl.amount_krw
                       for fl in st.portfolio.flows[1:]})  # 첫 입금(초기자금) 제외
        f = f.groupby(level=0).sum()
        flows_by_char[name] = f
        eq = equity[name]
        char_trades = trades[trades.character == name] if not trades.empty else trades
        summary[name] = {
            "twr": metrics.time_weighted_return(eq, f),
            "mdd": metrics.max_drawdown(eq),
            "pnl_krw": metrics.simple_pnl_krw(eq, f),
            "n_trades": int(len(char_trades)),
        }
    green_hist = pd.Series(green_counts).value_counts().sort_index()
    return ReplayResult(trades, equity, flows_by_char, green_hist, summary)
```

`simcore/report.py`:

```python
"""리플레이 결과 출력: CSV + 콘솔 요약 + docs/experiments 실험 기록."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import pandas as pd

from simcore.config import Config
from simcore.replay import ReplayResult


def write_outputs(result: ReplayResult, config: Config, out_dir: Path,
                  experiments_dir: Path | None = None,
                  benchmarks: dict[str, float] | None = None,
                  label: str = "replay") -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result.trades.to_csv(out / "trades.csv", index=False, encoding="utf-8-sig")
    result.equity.to_csv(out / "equity_curve.csv", encoding="utf-8-sig")
    result.green_hist.rename("count").to_csv(out / "signal_distribution.csv",
                                             encoding="utf-8-sig")
    lines = [f"# {label} 결과", "", "| 캐릭터 | TWR | MDD | 손익(KRW) | 거래수 |",
             "|---|---|---|---|---|"]
    for name, s in result.summary.items():
        lines.append(f"| {name} | {s['twr']:+.2%} | {s['mdd']:.2%} "
                     f"| {s['pnl_krw']:+,.0f} | {s['n_trades']} |")
    if benchmarks:
        lines += ["", "## 벤치마크 (매수후보유)", ""]
        lines += [f"- {k}: {v:+.2%}" for k, v in benchmarks.items()]
    lines += ["", "## 신호 분포 (청신호 개수별 종목-일 수)", "",
              result.green_hist.to_string(), "", "## 설정 스냅샷", "",
              "```python", repr(asdict(config)), "```"]
    text = "\n".join(lines)
    print(text)
    if experiments_dir is not None:
        exp = Path(experiments_dir)
        exp.mkdir(parents=True, exist_ok=True)
        seq = len(list(exp.glob(f"{label}_*.md"))) + 1
        (exp / f"{label}_{seq:03d}.md").write_text(text, encoding="utf-8")
```

`simcore/__main__.py` (CLI):

```python
"""리플레이 CLI: python -m simcore --start 2025-01-01 --end 2025-12-31"""
from __future__ import annotations
import argparse
from dataclasses import replace
from datetime import date
from pathlib import Path
import pandas as pd

from simcore.config import Config
from simcore import data as datamod, universe, metrics
from simcore.replay import DataBundle, FlowEvent, run_replay
from simcore.report import write_outputs


def parse_flows(path: str) -> list[FlowEvent]:
    df = pd.read_csv(path, dtype={"liquidate": str})
    out = []
    for _, r in df.iterrows():
        liq = tuple(str(r.get("liquidate", "")).split(";")) if pd.notna(r.get("liquidate")) and str(r.get("liquidate")) else ()
        out.append(FlowEvent(pd.Timestamp(r["date"]).date(), r["character"],
                             float(r["amount_krw"]), liq))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="simcore 과거 데이터 리플레이")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--flows", default=None, help="입출금 CSV (date,character,amount_krw,liquidate)")
    ap.add_argument("--buy-threshold", type=int, default=None)
    ap.add_argument("--kr-top", type=int, default=200, help="코스피200 중 앞 N종목")
    ap.add_argument("--us-top", type=int, default=100, help="S&P500 중 앞 N종목")
    ap.add_argument("--out", default="out")
    ap.add_argument("--cache", default="data/cache")
    args = ap.parse_args()

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    cfg = Config()
    if args.buy_threshold is not None:
        cfg = replace(cfg, rules=replace(cfg.rules, buy_threshold=args.buy_threshold))

    cache = Path(args.cache)
    kr_syms = universe.kospi200(cache, start)[: args.kr_top]
    us_syms = universe.sp500(cache)[: args.us_top]
    print(f"[universe] KR {len(kr_syms)}종목, US {len(us_syms)}종목 로딩 중...")
    bundle = DataBundle(
        kr=datamod.load_kr_daily(kr_syms, start, end, cache),
        us=datamod.load_us_daily(us_syms, start, end, cache),
        fx=datamod.load_fx(start, end, cache),
    )
    flows = parse_flows(args.flows) if args.flows else []
    result = run_replay(cfg, bundle, start, end, flows=flows)

    # 벤치마크: 매수후보유 (구간 첫 종가 → 마지막 종가)
    benchmarks = {}
    try:
        from pykrx import stock
        k200 = stock.get_index_ohlcv(f"{start:%Y%m%d}", f"{end:%Y%m%d}", "1028")["종가"]
        benchmarks["KOSPI200"] = float(k200.iloc[-1] / k200.iloc[0] - 1)
    except Exception as exc:
        print(f"[benchmark] KOSPI200 실패: {exc}")
    try:
        import yfinance as yf
        spx = yf.download("^GSPC", start=start, end=end, auto_adjust=True,
                          progress=False)["Close"].squeeze()
        benchmarks["S&P500"] = float(spx.iloc[-1] / spx.iloc[0] - 1)
    except Exception as exc:
        print(f"[benchmark] S&P500 실패: {exc}")

    write_outputs(result, cfg, Path(args.out),
                  experiments_dir=Path("docs/experiments"), benchmarks=benchmarks,
                  label=f"replay_{start}_{end}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인** — Run: `.venv\Scripts\python -m pytest tests\test_replay_integration.py -v` — Expected: 3 passed. 이어서 전체 `.venv\Scripts\python -m pytest -q` 통과.

- [ ] **Step 5: 커밋**

```powershell
git add simcore\replay.py simcore\report.py simcore\__main__.py tests\test_replay_integration.py
git commit -m "feat: 리플레이 오케스트레이션 + 결과 리포트 + CLI + 합성 통합테스트"
```

---

### Task 12: 실데이터 스모크 런 + 문서 마무리

**Files:**
- Create: `README.md`, `.env.example`, `docs/experiments/` 첫 기록(자동 생성)
- Modify: `docs/trading-rules.md` (구현과 다르게 확정된 부분이 있으면 갱신)

**Interfaces:**
- Consumes: Task 11 CLI
- Produces: 실행 가능한 프로젝트 문서화 + 첫 실험 기록

- [ ] **Step 1: 소규모 실데이터 스모크 런** (네트워크 필요, 캐시 생성 겸용)

Run: `.venv\Scripts\python -m simcore --start 2025-09-01 --end 2025-12-31 --kr-top 30 --us-top 30`
Expected: 콘솔에 3캐릭터 요약표 + 신호 분포 + 벤치마크 출력, `out/trades.csv`·`out/equity_curve.csv`·`out/signal_distribution.csv` 생성, `docs/experiments/replay_*_001.md` 생성. 임계값 7에서 거래가 0건에 가까울 수 있음 — 신호 분포를 보고 `--buy-threshold 5` 로 재실행해 거래 발생 확인.

- [ ] **Step 2: 결과 검토 및 기록**

신호 분포(청신호 개수 히스토그램)를 확인하고, 임계값별 거래 빈도 관찰을 experiments 기록에 코멘트로 남긴다(자동 생성 파일에 한 줄 추가 가능).

- [ ] **Step 3: README.md 작성**

```markdown
# simcore — 규칙 기반 롱온리 모의투자 시뮬레이터 (엔진 코어)

청신호/적신호 카운트 규칙(매수 7 / 매도 3)으로 3캐릭터(국내형/해외형/범용형)가
각 1억 원으로 모의매매하는 엔진. 과거 데이터 리플레이로 검증한다.

## 설치
    py -m venv .venv
    .venv\Scripts\python -m pip install -e .[dev]

## 리플레이 실행
    .venv\Scripts\python -m simcore --start 2025-01-01 --end 2025-12-31
    # 옵션: --buy-threshold 5  --kr-top 50 --us-top 50  --flows flows.csv  --out out

입출금 CSV 형식: `date,character,amount_krw,liquidate` (liquidate 는 세미콜론 구분 종목코드, 출금 시 청산 지정)

## 테스트
    .venv\Scripts\python -m pytest

## 문서
- 매매 규칙(튜닝 기준): docs/trading-rules.md
- 설계 스펙: docs/superpowers/specs/2026-07-07-simcore-engine-design.md
- 실험 기록: docs/experiments/

## 주의
실제 매매가 아닌 페이퍼 트레이딩이며 투자 조언이 아닙니다.
```

- [ ] **Step 4: .env.example 작성** (다음 서브프로젝트 대비 변수 목록만)

```
# 한국투자증권 KIS 오픈API — 값은 .env 에만 직접 입력 (커밋 금지)
KIS_APP_KEY=
KIS_APP_SECRET=
KIS_ACCOUNT_NO=
KIS_ENV=paper
```

- [ ] **Step 5: 전체 테스트 + 최종 커밋**

Run: `.venv\Scripts\python -m pytest -q` — Expected: all passed

```powershell
git add README.md .env.example docs
git commit -m "docs: README/.env.example + 첫 리플레이 실험 기록"
```

---

## 셀프 리뷰 결과 (계획 작성 후 점검)

- **스펙 커버리지:** 3캐릭터·신호 14개(활성)+4개(스텁 컬럼)·7/3 규칙·손절우선·다음날 시가 체결·쿨다운·사이징·비용·환율·입출금(TWR)·신호분포 리포트·벤치마크·experiments 기록 — 각각 Task 1~12 에 대응. 라이브 모드는 범위 밖(스펙 10장)으로 이번 계획에 없음이 맞다.
- **타입 일관성:** `SymbolSnapshot`/`DailyBar`/`FlowEvent` 시그니처를 Interfaces 블록 기준으로 통일했다. 구현 중 불일치 발견 시 Interfaces 블록이 기준.
- **알려진 근사(의도된 것):** 같은 달력일의 KR·US 세션을 한 스텝으로 처리(일 단위 근사), 리플레이 손익절은 OHLC 근사·손절 우선, 벤치마크는 가격수익률(배당 제외).
