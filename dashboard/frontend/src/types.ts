// 백엔드 pydantic 스키마(dashboard/backend/schemas.py)를 그대로 미러링한 TS 타입.
// 날짜/일시 필드는 JSON 직렬화 기준 문자열(ISO 8601)로 받는다.

export interface CardSummary {
  name: string;
  base_currency: string;
  markets: string[];
  benchmark_delta: number | null;
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
