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
    # 의사결정판 확장 필드(감사 Phase B) — SignalStatusRow(kind=보유)가 없는 종목/캐릭터는
    # 신호 관련 필드가 전부 null 이다(500 방지, "관찰 데이터 없음"을 있는 그대로 노출).
    weight_pct: float | None = None
    entry_trigger: str = ""
    current_red_score: int | None = None
    stop_px: float | None = None
    trail_px: float | None = None
    stop_distance_pct: float | None = None
    potential_loss: float | None = None
    pending_sell: bool = False
    as_of: date | None = None


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


class TradesPage(BaseModel):
    """거래 내역 페이지 — items(현재 페이지)와 total(필터 기준 전체 건수)."""
    items: list[TradeOut]
    total: int


class LifecycleOut(BaseModel):
    """포지션 생애(진입→청산) — 종목별 보유수량 0→BUY 시작, 0 도달 SELL로 종료."""
    symbol: str
    name: str
    market: str
    entry_date: date
    exit_date: date | None = None
    open: bool
    trades: list[TradeOut]
    qty_peak: int
    realized_pnl_sum: float
    entry_trigger: str


class CandidateOut(BaseModel):
    """오늘의 매수후보(SignalStatusRow kind=후보) — 의사결정판(감사 Phase B)."""
    symbol: str
    name: str
    market: str
    green_score: int
    red_score: int
    buy_gate: bool
    status: str          # "예약" | "차단"
    block_reason: str    # "점수부족"|"게이트미충족"|"보유중"|"쿨다운"|"슬롯부족"|"현금부족"|"가격없음"|""
    as_of: date
    close: float | None = None


class MarketStatusOut(BaseModel):
    """시장별 데이터 기준(run_state) — as-of 표시용(P0)."""
    market: str
    last_close_date: str | None = None
    last_open_date: str | None = None


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


class PendingOrderOut(BaseModel):
    """대기주문(BUY/SELL 결정) — today_actions 용."""
    symbol: str
    name: str
    market: str
    side: str
    decision_type: str = ""
    trigger_rule: str = ""
    reason: str = ""


class ForcedSellAlertOut(BaseModel):
    """최신 거래일에 발생한 강제청산 경보 — today_actions 용."""
    symbol: str
    name: str
    market: str
    date: date
    realized_pnl: float


class TodayActionsOut(BaseModel):
    """캐릭터별 오늘의 결정(대기주문) + 최신일 강제청산 경보."""
    character: str
    pending_orders: list[PendingOrderOut]
    forced_sell_alerts: list[ForcedSellAlertOut]


class CharacterRiskOut(BaseModel):
    """캐릭터별 포트폴리오 위험: 현금비중·총노출·최대 보유 비중(종목 집중)·일 손익.
    "업종 집중"이 아니다 — 업종/실적일 데이터가 없다."""
    character: str
    cash_ratio: float
    total_exposure_pct: float
    max_position_weight_pct: float
    daily_pnl_krw: float


class DashboardOut(BaseModel):
    """일일 현황판 응답."""
    movers: dict[str, dict[str, list[MoverOut]]]
    characters: list[CharPortfolioOut]
    recent_trades: list[RecentTradeOut]
    # 의사결정판 확장(감사 Phase B) — 필드 추가 방식이라 기존 소비처는 영향 없음.
    today_actions: list[TodayActionsOut] = []
    risk: list[CharacterRiskOut] = []
