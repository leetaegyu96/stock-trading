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
