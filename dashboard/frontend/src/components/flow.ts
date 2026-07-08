// 입출금 모달(FlowModal) 금액 검증 순수 함수. 콤마/공백이 섞인 입력을 허용하고,
// 숫자로 해석할 수 없거나 0 이하이면 무효로 취급한다.

/** 사용자가 입력한 금액 문자열을 숫자로 변환. 파싱 불가하면 null. */
export function parseAmountInput(raw: string): number | null {
  const cleaned = raw.replace(/[,\s]/g, "");
  if (cleaned === "") return null;
  if (!/^\d+(\.\d+)?$/.test(cleaned)) return null;
  const value = Number(cleaned);
  if (!Number.isFinite(value)) return null;
  return value;
}

/** 0보다 큰 유효한 금액인지 (null 포함) 판별. */
export function isPositiveAmount(value: number | null): value is number {
  return value !== null && value > 0;
}
