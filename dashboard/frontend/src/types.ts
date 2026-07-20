// 백엔드 pydantic 스키마(dashboard/backend/schemas.py)를 그대로 미러링한 TS 타입.
// 날짜/일시 필드는 JSON 직렬화 기준 문자열(ISO 8601)로 받는다.

export interface CardSummary {
  name: string;
  base_currency: string;
  markets: string[];
  benchmark_delta: number | null;
  benchmark_available: boolean;
  total_asset_krw: number;
  twr: number;
  pnl_krw: number;
  today_pnl_pct: number;
  equity_spark: number[];
  n_positions: number;
  cash_krw: number;
}

export interface Metrics {
  twr: number;
  mdd: number;
  n_trades: number;
  win_rate: number;
  pnl_krw: number;
  // 위험조정 지표(P0-3) — 무위험수익률 0 가정. simcore.metrics.risk_metrics 미러링.
  cagr: number;
  volatility: number;
  sharpe: number;
  sortino: number;
  calmar: number;
  profit_factor: number;
  avg_win: number;
  avg_loss: number;
  win_loss_ratio: number;
  expectancy: number;
  max_consecutive_losses: number;
  recovery_days: number;
  // 벤치마크 대비 초과수익 — benchmark_available=false면 return/delta는 null이고
  // 화면은 이를 "집계 실패" 경고로 표시해야 한다(조용히 숨기지 않음, P0-3).
  benchmark_return: number | null;
  benchmark_delta: number | null;
  benchmark_name: string;
  benchmark_available: boolean;
}

export interface PositionOut {
  symbol: string;
  name: string;
  market: string;
  quantity: number;
  avg_price: number;
  opened_date: string;
  current_price: number | null;
  eval_value: number | null;
  pnl_pct: number | null;
  stale: boolean | null;
  // 의사결정판 확장 필드(감사 Phase B) — SignalStatusRow(kind=보유)가 없는 종목/캐릭터는
  // 신호 관련 필드가 전부 null 이다(500 방지, "관찰 데이터 없음"을 있는 그대로 노출).
  weight_pct: number | null;
  entry_trigger: string;
  current_red_score: number | null;
  stop_px: number | null;
  trail_px: number | null;
  stop_distance_pct: number | null;
  potential_loss: number | null;
  pending_sell: boolean;
  as_of: string | null;
}

/** 오늘의 매수후보(SignalStatusRow kind=후보) — 의사결정판(감사 Phase B). */
export interface CandidateOut {
  symbol: string;
  name: string;
  market: string;
  green_score: number;
  red_score: number;
  buy_gate: boolean;
  status: string; // "예약" | "차단"
  block_reason: string; // "점수부족"|"게이트미충족"|"보유중"|"쿨다운"|"슬롯부족"|"현금부족"|"가격없음"|""
  as_of: string;
  close: number | null;
}

export interface SignalDetail {
  code: string;
  name: string;
  category: string;
  stars: number;
}

export interface TradeOut {
  ts: string;
  date: string;
  symbol: string;
  name: string;
  market: string;
  side: string;
  quantity: number;
  price: number;
  fee: number;
  tax: number;
  reason: string;
  green_count: number;
  red_count: number;
  green_score: number;
  red_score: number;
  fired: string[];
  signal_summary: string;
  signal_detail: SignalDetail[];
  realized_pnl: number;
  // 결정 기반 표시(P0-1): BUY/PARTIAL_SELL/FULL_SELL/FORCED_SELL. signal_summary는
  // 이미 이 값을 반영한 결정기반 문구이므로 프론트에서 red_score로 재계산하지 않는다.
  decision_type: string;
  trigger_rule: string;
}

/** 거래 내역 페이지 — items(현재 페이지)와 total(필터 기준 전체 건수). */
export interface TradesPage {
  items: TradeOut[];
  total: number;
}

/** 거래 조회 필터/페이지네이션 쿼리 파라미터. */
export interface TradesQuery {
  limit?: number;
  offset?: number;
  symbol?: string;
  side?: string;
  decision_type?: string;
  date_from?: string;
  date_to?: string;
}

/** 포지션 생애(진입→청산) — 종목별 보유수량 0→BUY 시작, 0 도달 SELL로 종료. */
export interface LifecycleOut {
  symbol: string;
  name: string;
  market: string;
  entry_date: string;
  exit_date: string | null;
  open: boolean;
  trades: TradeOut[];
  qty_peak: number;
  realized_pnl_sum: number;
  entry_trigger: string;
}

export interface FlowOut {
  date: string;
  amount_krw: number;
  fx_rate: number;
}

export interface EquityPoint {
  ts: string;
  equity_krw: number;
}

export interface Mover {
  symbol: string;
  name: string;
  market: string;
  change_pct: number;
  close: number;
}

export interface HoldingRank {
  symbol: string;
  name: string;
  market: string;
  close: number;
  pnl_pct: number;
}

export interface CharPortfolio {
  name: string;
  today_pnl_pct: number;
  n_positions: number;
  best: HoldingRank | null;
  worst: HoldingRank | null;
}

export interface RecentTrade {
  character: string;
  symbol: string;
  name: string;
  market: string;
  side: string;
  reason: string;
  realized_pnl: number;
  date: string;
}

/** 대기주문(BUY/SELL 결정) — today_actions 용. */
export interface PendingOrderOut {
  symbol: string;
  name: string;
  market: string;
  side: string;
  decision_type: string;
  trigger_rule: string;
  reason: string;
}

/** 최신 거래일에 발생한 강제청산 경보 — today_actions 용. */
export interface ForcedSellAlertOut {
  symbol: string;
  name: string;
  market: string;
  date: string;
  realized_pnl: number;
}

/** 캐릭터별 오늘의 결정(대기주문) + 최신일 강제청산 경보. */
export interface TodayActionsOut {
  character: string;
  pending_orders: PendingOrderOut[];
  forced_sell_alerts: ForcedSellAlertOut[];
}

/** 캐릭터별 포트폴리오 위험: 현금비중·총노출·최대 보유 비중(종목 집중)·일 손익.
 * "업종 집중"이 아니다 — 업종/실적일 데이터가 없다. */
export interface CharacterRiskOut {
  character: string;
  cash_ratio: number;
  total_exposure_pct: number;
  max_position_weight_pct: number;
  daily_pnl_krw: number;
}

export interface Dashboard {
  movers: Record<string, { up: Mover[]; down: Mover[] }>;
  characters: CharPortfolio[];
  recent_trades: RecentTrade[];
  // 의사결정판 확장(감사 Phase B) — 필드 추가 방식이라 기존 소비처는 영향 없음.
  today_actions: TodayActionsOut[];
  risk: CharacterRiskOut[];
}

/** 시장별 데이터 기준(run_state 미러) — as-of 표시용(P0). */
export interface MarketStatus {
  market: string;
  last_close_date: string | null;
  last_open_date: string | null;
}
