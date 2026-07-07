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
