"""대시보드 API 응답 스키마 (pydantic)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class CardSummary(BaseModel):
    """캐릭터 카드 요약."""
    total_asset_krw: float
    twr: float
    pnl_krw: float
    today_pnl_pct: float
    equity_spark: list[float]
    n_positions: int
    cash_krw: float


class Metrics(BaseModel):
    """캐릭터 상세 성과 지표."""
    twr: float
    mdd: float
    n_trades: int
    win_rate: float
    pnl_krw: float


class PositionOut(BaseModel):
    symbol: str
    market: str
    quantity: int
    avg_price: float
    opened_date: date


class TradeOut(BaseModel):
    ts: datetime
    date: date
    symbol: str
    market: str
    side: str
    quantity: int
    price: float
    fee: float
    tax: float
    reason: str
    green_count: int
    red_count: int
    fired: list[str]
    realized_pnl: float


class FlowOut(BaseModel):
    date: date
    amount_krw: float
    fx_rate: float


class EquityPoint(BaseModel):
    ts: datetime
    equity_krw: float
