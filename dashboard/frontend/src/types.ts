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
  market: string;
  quantity: number;
  avg_price: number;
  opened_date: string;
  current_price: number | null;
  eval_value: number | null;
  pnl_pct: number | null;
  stale: boolean | null;
}

export interface TradeOut {
  ts: string;
  date: string;
  symbol: string;
  market: string;
  side: string;
  quantity: number;
  price: number;
  fee: number;
  tax: number;
  reason: string;
  green_count: number;
  red_count: number;
  fired: string[];
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
