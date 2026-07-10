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

export interface Dashboard {
  movers: Record<string, { up: Mover[]; down: Mover[] }>;
  characters: CharPortfolio[];
  recent_trades: RecentTrade[];
}

/** 시장별 데이터 기준(run_state 미러) — as-of 표시용(P0). */
export interface MarketStatus {
  market: string;
  last_close_date: string | null;
  last_open_date: string | null;
}
