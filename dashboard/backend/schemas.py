"""대시보드 API 응답 스키마 (pydantic)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class CardSummary(BaseModel):
    """캐릭터 카드 요약."""
    name: str
    base_currency: str
    markets: list[str]
    benchmark_delta: float | None = None
    benchmark_available: bool = False
    total_asset_krw: float
    twr: float
    pnl_krw: float
    today_pnl_pct: float
    equity_spark: list[float]
    n_positions: int
    cash_krw: float


class Metrics(BaseModel):
    """캐릭터 상세 성과 지표(기본) + 위험조정 지표 + 벤치마크 대비.

    benchmark_* 는 seed_from_replay 가 미리 적재한 BenchmarkRow 스냅샷 기반이다.
    시딩 안 됐으면(benchmark_available=False) return/delta 는 None — 화면이 이를
    '집계 실패'로 경고해야 하며, 조용히 숨기면 안 된다(P0-3)."""
    twr: float
    mdd: float
    n_trades: int
    win_rate: float
    pnl_krw: float
    cagr: float = 0.0
    volatility: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_loss_ratio: float = 0.0
    expectancy: float = 0.0
    max_consecutive_losses: int = 0
    recovery_days: int = 0
    benchmark_return: float | None = None
    benchmark_delta: float | None = None
    benchmark_name: str = ""
    benchmark_available: bool = False


class PositionOut(BaseModel):
    symbol: str
    name: str
    market: str
    quantity: int
    avg_price: float
    opened_date: date
    current_price: float | None = None
    eval_value: float | None = None
    pnl_pct: float | None = None
    stale: bool | None = None


class TradeOut(BaseModel):
    ts: datetime
    date: date
    symbol: str
    name: str
    market: str
    side: str
    quantity: int
    price: float
    fee: float
    tax: float
    reason: str
    green_count: int
    red_count: int
    green_score: int = 0
    red_score: int = 0
    fired: list[str]
    signal_summary: str = ""
    signal_detail: list[dict] = []
    realized_pnl: float
    decision_type: str = "BUY"
    trigger_rule: str = ""


class FlowOut(BaseModel):
    date: date
    amount_krw: float
    fx_rate: float


class EquityPoint(BaseModel):
    ts: datetime
    equity_krw: float


class MoverOut(BaseModel):
    """유니버스 등락률 상/하위 종목."""
    symbol: str
    name: str
    market: str
    change_pct: float
    close: float


class HoldingRank(BaseModel):
    """캐릭터 보유 베스트/워스트 종목."""
    symbol: str
    name: str
    pnl_pct: float


class CharPortfolioOut(BaseModel):
    """캐릭터별 일일 현황판 요약."""
    name: str
    today_pnl_pct: float
    n_positions: int
    best: HoldingRank | None = None
    worst: HoldingRank | None = None


class RecentTradeOut(BaseModel):
    """통합 최신 체결."""
    character: str
    symbol: str
    name: str
    market: str
    side: str
    reason: str
    realized_pnl: float
    date: date


class DashboardOut(BaseModel):
    """일일 현황판 응답."""
    movers: dict[str, dict[str, list[MoverOut]]]
    characters: list[CharPortfolioOut]
    recent_trades: list[RecentTradeOut]
