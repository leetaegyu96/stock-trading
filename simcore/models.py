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
    TRAILING_STOP = "TRAILING_STOP"


class DecisionType(str, Enum):
    BUY = "BUY"
    PARTIAL_SELL = "PARTIAL_SELL"
    FULL_SELL = "FULL_SELL"
    FORCED_SELL = "FORCED_SELL"
    INTRADAY_BUY = "INTRADAY_BUY"
    INTRADAY_SELL = "INTRADAY_SELL"


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
    peak_price: float = 0.0
    locked_stop_pct: float = 0.0


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
    green_score: int = 0
    red_score: int = 0
    realized_pnl: float = 0.0  # 시장 통화, 비용 차감 후
    decision_type: DecisionType = DecisionType.BUY
    trigger_rule: str = ""


@dataclass(frozen=True)
class CapitalFlow:
    date: Date
    character: str
    amount_krw: float  # 입금 +, 출금 −
    fx_rate: float


@dataclass(frozen=True)
class CandidateEval:
    """장 마감 매수 후보 평가 기록(관찰 전용) — 매매 결정에는 사용되지 않는다."""
    symbol: str
    market: Market
    green_score: int
    red_score: int
    buy_gate: bool
    status: str            # "예약" | "차단"
    block_reason: str = ""  # 예약이면 ""


@dataclass(frozen=True)
class SymbolSnapshot:
    """장 마감 후 종목 하나의 신호 판정 결과. 엔진은 이것만 소비한다."""
    symbol: str
    market: Market
    green: tuple[str, ...]
    red: tuple[str, ...]  # 시장 데이터 기반 적신호 코드. R7 손절/트레일링은 엔진이 포지션
                          # 가격으로 별도 판정하며 이 튜플에 넣지 않는다(v2: R10/익절 폐지).
    close: float
    change_pct: float
    volume: float
    green_score: int = 0
    red_score: int = 0
    buy_gate: bool = False
