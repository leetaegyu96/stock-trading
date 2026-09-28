// SPEC §7(API 계약) · §4.2(종목 필드) 의 응답 타입.
//
// 금액 단위 약속: DB 는 최소단위 정수(원/센트)로 저장하지만(SPEC §2.1), **API 경계에서는
// 사람이 읽는 단위**로 내려온다 — KRW 는 원(정수), USD 는 달러(소수 2자리).
// 따라서 프론트는 minor 단위를 절대 다루지 않는다. 통화 구분은 `currency` 필드로 한다.

export type AccountKind = "KR" | "US";
export type Currency = "KRW" | "USD";
export type Side = "BUY" | "SELL";
/** 체결 사유. MANUAL = 사람이 누른 매수·매도, AUTO_* = 매도벽 발동(SPEC §6.2). */
export type TradeReason = "MANUAL" | "AUTO_STOP_LOSS" | "AUTO_TAKE_PROFIT";

/** 오류 규약(SPEC §7). message 는 초보가 읽을 한국어 문장이 그대로 온다. */
export type ApiErrorCode =
  | "UNAUTHORIZED"
  | "FORBIDDEN"
  | "NOT_FOUND"
  | "INSUFFICIENT_CASH"
  | "INSUFFICIENT_QUANTITY"
  | "INVALID_QUANTITY"
  | "INVALID_SELL_RULE"
  | "PRICE_UNAVAILABLE"
  | "MARKET_MISMATCH"
  | "RATE_LIMITED"
  /** 400 — 약한 비밀번호·이메일 형식 등 입력 유효성 */
  | "INVALID_INPUT"
  /** 409 — 이미 가입된 이메일 */
  | "EMAIL_TAKEN";

export interface ApiErrorBody {
  error: { code: ApiErrorCode | string; message: string };
}

// ── 인증 ────────────────────────────────────────────────────────────────
export interface Me {
  id: number;
  email: string;
  nickname: string;
}

export interface SignupRequest {
  email: string;
  password: string;
  nickname: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

// ── 계좌(캐릭터) ─────────────────────────────────────────────────────────
export interface EquityPoint {
  /** ISO8601 */
  ts: string;
  equity: number;
}

export interface AccountSummary {
  id: number;
  kind: AccountKind;
  currency: Currency;
  /** 현금 잔고 */
  cash: number;
  /** 보유 종목 평가액 합 */
  market_value: number;
  /** cash + market_value */
  total_asset: number;
  /** 최초 투입액 = 수익률 분모 */
  seed: number;
  /** total_asset - seed */
  pnl: number;
  /** 수익률 % (예: -3.2 = -3.2%) */
  return_pct: number;
  position_count: number;
  /** 자산곡선 스파크라인용 최근 equity 배열(오래된 → 최신) */
  equity_spark: number[];
  /** 시세 조회 실패로 캐시값을 섞어 계산했으면 true */
  stale: boolean;
}

export interface AccountDetail extends AccountSummary {
  equity_curve: EquityPoint[];
}

// ── 매도벽 ───────────────────────────────────────────────────────────────
export interface SellRule {
  id: number;
  position_id: number;
  /** 음수 % (예: -5). 미설정이면 null */
  stop_loss_pct: number | null;
  /** 양수 % (예: 15). 미설정이면 null */
  take_profit_pct: number | null;
  /** 서버가 평단 기준으로 계산해 내려주는 발동가 — 프론트는 표시만 한다 */
  stop_price: number | null;
  take_price: number | null;
  /** 발동 시 팔 수량 */
  quantity: number;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SellRuleRequest {
  stop_loss_pct?: number | null;
  take_profit_pct?: number | null;
  quantity?: number;
}

// ── 보유 종목 ────────────────────────────────────────────────────────────
export interface Position {
  id: number;
  account_id: number;
  symbol: string;
  name: string;
  quantity: number;
  /** 매수 수수료를 포함한 평단(SPEC §5.1) */
  avg_price: number;
  current_price: number;
  /** quantity * current_price */
  market_value: number;
  /** quantity * avg_price */
  cost_basis: number;
  /** market_value - cost_basis */
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  opened_at: string;
  /** 현재가가 실시간 조회 실패해 캐시값인 경우 */
  stale: boolean;
  sell_rule: SellRule | null;
}

// ── 시세 ────────────────────────────────────────────────────────────────
/** SPEC §4.2 종목 리스트 1행. 점수·추천 필드는 v2 에 존재하지 않는다. */
export interface Stock {
  symbol: string;
  name: string;
  price: number;
  /** 전일 종가 대비 등락률 % */
  change_pct: number;
  /** 최근 7거래일 종가(오래된 → 최신) */
  spark7: number[];
  /** 7일 전 대비 등락률 % */
  week_change_pct: number;
  volume: number;
  /** 20일 평균 거래량 대비 배수 (1.0 = 평소 수준) */
  volume_vs_avg: number;
  high_52w: number;
  low_52w: number;
  stale: boolean;
}

export interface DailyBar {
  /** YYYY-MM-DD */
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface StockDetail extends Stock {
  kind: AccountKind;
  currency: Currency;
  /** 최근 30거래일 일봉(오래된 → 최신) */
  bars30: DailyBar[];
}

// ── 체결·활동 ────────────────────────────────────────────────────────────
export interface Trade {
  id: number;
  account_id: number;
  symbol: string;
  name: string;
  side: Side;
  quantity: number;
  /** 체결 단가 */
  price: number;
  fee: number;
  tax: number;
  /** quantity * price */
  gross: number;
  /** 현금 증감(매수는 음수, 매도는 양수) */
  net: number;
  /** SELL 만. 비용 차감 후 실현손익 */
  realized_pnl: number | null;
  reason: TradeReason;
  sell_rule_id: number | null;
  /**
   * 자동매도의 발동선 가격. SPEC §6.2 는 "발동선과 실제 체결가를 나란히 표시"하라고
   * 요구하므로 체결가(price)와 별도로 필요하다. MANUAL 이면 null.
   */
  trigger_price: number | null;
  executed_at: string;
}

export interface TradesPage {
  items: Trade[];
  total: number;
}

export interface TradesQuery {
  limit?: number;
  offset?: number;
  symbol?: string;
  side?: Side;
  reason?: TradeReason;
}

export interface EventLog {
  id: number;
  account_id: number | null;
  kind: string;
  detail: Record<string, unknown>;
  ts: string;
}

// ── 주문 ────────────────────────────────────────────────────────────────
export interface OrderRequest {
  symbol: string;
  quantity: number;
}

/**
 * 매수·매도 응답. 체결 1건 + 갱신된 계좌 요약 + 갱신된 포지션(전량 매도면 null)을
 * 한 번에 돌려주어, 프론트가 확정 직후 화면을 다시 조회하지 않아도 되게 한다.
 */
export interface OrderResult {
  trade: Trade;
  account: AccountSummary;
  position: Position | null;
}

/** 종목 목록 한 페이지. 상세는 요청 구간만 채워지므로 서버가 전체 개수를 따로 알려준다. */
export interface StocksPage {
  items: Stock[];
  total: number;
  offset: number;
  limit: number;
}

// ── 랭킹 ─────────────────────────────────────────────────────────────────
/** 랭킹 탭. "all" 은 국내·해외를 한 표에 섞어 본다. */
export type RankingKind = "all" | AccountKind;

/**
 * 랭킹 1행(`GET /api/ranking`). 서버가 **일간 수익률 내림차순으로 정렬**해서 준다.
 *
 * 금액(daily_pnl·total_asset)은 계좌 통화 그대로다 — 국내는 원, 해외는 달러라
 * 서로 더하거나 비교할 수 없다. 그래서 순위 기준은 금액이 아니라 비율(%)이다.
 * 개인정보는 닉네임만 온다(이메일은 서버가 내려주지 않는다).
 */
export interface RankingRow {
  /** 1부터. 동률은 누적 수익률로 가른다(서버 규칙). */
  rank: number;
  account_id: number;
  /** 표시 이름 */
  nickname: string;
  kind: AccountKind;
  currency: Currency;
  /** 순위 기준 — 어제 마감 대비 오늘 수익률 % */
  daily_return_pct: number;
  /** 오늘 손익 (해당 통화, 사람 단위) */
  daily_pnl: number;
  /** 처음 투입액 대비 누적 수익률 % */
  total_return_pct: number;
  /** 현재 총자산 (해당 통화) */
  total_asset: number;
  position_count: number;
  /** 내 계정이면 true */
  is_me: boolean;
  /** 시세가 최신이 아니라 일부를 평단으로 계산했으면 true */
  stale: boolean;
}
