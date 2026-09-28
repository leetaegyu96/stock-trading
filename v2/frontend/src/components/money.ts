// 매수·매도 예상금액 계산 (SPEC §2.3 비용 모델).
//
// 백엔드 `v2/backend/money.py` 와 **같은 값·같은 반올림**을 써야 화면의 예상금액과
// 실제 체결이 어긋나지 않는다. 반올림은 최소단위(KRW=원, USD=센트) 기준 round-half-up.
import type { AccountKind, Currency } from "../types";

export const FEE_RATE: Record<AccountKind, number> = { KR: 0.00015, US: 0.0009 };
/** 매도세(증권거래세)는 국내만. 매수에는 붙지 않는다. */
export const TAX_RATE: Record<AccountKind, number> = { KR: 0.0015, US: 0 };

function minorPerUnit(currency: Currency): number {
  return currency === "USD" ? 100 : 1;
}

/** 최소단위 기준 round-half-up. 음수는 다루지 않는다(금액·비용은 항상 0 이상). */
export function roundMinor(value: number, currency: Currency): number {
  const m = minorPerUnit(currency);
  // 0.5 를 올림으로 보내려면 부동소수 오차를 한 번 걷어내야 한다(예: 1.005*100=100.49999).
  const scaled = Number((value * m).toFixed(6));
  return Math.floor(scaled + 0.5) / m;
}

export interface BuyEstimate {
  /** 수량 × 단가 */
  gross: number;
  fee: number;
  /** 실제로 빠져나갈 현금 = gross + fee */
  total: number;
}

export function estimateBuy(
  price: number,
  quantity: number,
  kind: AccountKind,
  currency: Currency
): BuyEstimate {
  const gross = roundMinor(price * quantity, currency);
  const fee = roundMinor(gross * FEE_RATE[kind], currency);
  return { gross, fee, total: roundMinor(gross + fee, currency) };
}

export interface SellEstimate {
  gross: number;
  fee: number;
  tax: number;
  /** 손에 들어올 현금 = gross − fee − tax */
  net: number;
}

export function estimateSell(
  price: number,
  quantity: number,
  kind: AccountKind,
  currency: Currency
): SellEstimate {
  const gross = roundMinor(price * quantity, currency);
  const fee = roundMinor(gross * FEE_RATE[kind], currency);
  const tax = roundMinor(gross * TAX_RATE[kind], currency);
  return { gross, fee, tax, net: roundMinor(gross - fee - tax, currency) };
}

/** 매도 실현손익 = (체결가 − 평단) × 수량 − 수수료 − 세금 (SPEC §6.1). */
export function estimateRealizedPnl(
  price: number,
  avgPrice: number,
  quantity: number,
  kind: AccountKind,
  currency: Currency
): number {
  const { fee, tax } = estimateSell(price, quantity, kind, currency);
  return roundMinor((price - avgPrice) * quantity - fee - tax, currency);
}

/**
 * 현금으로 살 수 있는 최대 수량. 수수료까지 포함해 계산하고, 반올림 때문에 1주가
 * 넘치는 경우가 있으므로 마지막에 실제 견적으로 한 번 더 확인해 깎는다.
 */
export function maxAffordableQuantity(
  cash: number,
  price: number,
  kind: AccountKind,
  currency: Currency
): number {
  if (!(price > 0) || !(cash > 0)) return 0;
  let qty = Math.floor(cash / (price * (1 + FEE_RATE[kind])));
  while (qty > 0 && estimateBuy(price, qty, kind, currency).total > cash) qty -= 1;
  return Math.max(0, qty);
}

/** 매수 가능 여부 + 거부 사유(초보가 읽을 한국어). 버튼 비활성 판정에 쓴다. */
export function buyBlockReason(
  quantity: number,
  cash: number,
  price: number,
  kind: AccountKind,
  currency: Currency
): string | null {
  if (!Number.isInteger(quantity) || quantity <= 0) return "살 수량을 1주 이상 입력하세요.";
  if (!(price > 0)) return "현재가를 불러오지 못해 지금은 살 수 없습니다.";
  if (estimateBuy(price, quantity, kind, currency).total > cash) {
    return "가진 현금보다 많습니다. 수량을 줄여보세요.";
  }
  return null;
}

/** 매도 가능 여부 + 거부 사유. */
export function sellBlockReason(quantity: number, held: number, price: number): string | null {
  if (!Number.isInteger(quantity) || quantity <= 0) return "팔 수량을 1주 이상 입력하세요.";
  if (quantity > held) return `가진 수량(${held.toLocaleString("ko-KR")}주)보다 많습니다.`;
  if (!(price > 0)) return "현재가를 불러오지 못해 지금은 팔 수 없습니다.";
  return null;
}
