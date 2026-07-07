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
