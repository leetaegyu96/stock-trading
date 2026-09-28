// 매도벽(자동매도) 계산 — SPEC §6.2 / §8.2.
//
// 발동가는 **평단 기준**이다(매수가가 아니라). 추가 매수로 평단이 움직이면 벽도
// 자연스럽게 따라가야 하기 때문이다.
import type { AccountKind, Currency } from "../types";
import { roundMinor } from "./money";

/** 손절선/익절선 발동가. pct 가 null 이면 해당 선은 없다. */
export function triggerPrice(
  avgPrice: number,
  pct: number | null | undefined,
  currency: Currency
): number | null {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return null;
  return roundMinor(avgPrice * (1 + pct / 100), currency);
}

export interface GaugeInput {
  avgPrice: number;
  currentPrice: number;
  /** 하한선(이만큼 떨어지면 팔기) 발동가. 미설정이면 null */
  stopPrice: number | null;
  /** 상한선(이만큼 오르면 팔기) 발동가. 미설정이면 null */
  takePrice: number | null;
}

export interface GaugeResult {
  /** 게이지 왼쪽 끝 가격 */
  lo: number;
  /** 게이지 오른쪽 끝 가격 */
  hi: number;
  /** 각 지점의 막대 내 위치(0~100, %) */
  currentPos: number;
  avgPos: number;
  stopPos: number | null;
  takePos: number | null;
  /** 현재가가 이미 발동 조건을 넘었는가. 동시 충족이면 손절 우선(SPEC §6.2). */
  triggered: "stop" | "take" | null;
  /** 현재가가 설정한 두 벽 바깥이라 눈금을 넓혔는가 */
  widened: boolean;
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, value));
}

/**
 * 게이지 좌표 계산.
 *
 *   손절 9,500 ┃━━━━━●━━━━━━┃ 익절 11,500
 *
 * 기본 구간은 [손절가, 익절가]. 한쪽만 설정했으면 평단을 중심으로 반대쪽을 대칭으로
 * 잡아, 벽이 하나뿐일 때도 막대가 한쪽으로 쏠리지 않게 한다. 현재가가 구간 밖이면
 * (이미 발동선을 넘어섰거나 감시 전인 경우) 눈금을 넓혀 점이 끝에 붙어 숨지 않게 한다.
 */
export function sellWallGauge(input: GaugeInput): GaugeResult {
  const { avgPrice, currentPrice, stopPrice, takePrice } = input;

  let lo: number;
  let hi: number;
  if (stopPrice !== null && takePrice !== null) {
    lo = stopPrice;
    hi = takePrice;
  } else if (stopPrice !== null) {
    lo = stopPrice;
    hi = avgPrice + (avgPrice - stopPrice);
  } else if (takePrice !== null) {
    lo = avgPrice - (takePrice - avgPrice);
    hi = takePrice;
  } else {
    // 벽이 전혀 없으면 평단 ±10% 를 참고 눈금으로 보여준다.
    lo = avgPrice * 0.9;
    hi = avgPrice * 1.1;
  }

  const baseSpan = hi - lo || Math.abs(avgPrice) || 1;
  const margin = baseSpan * 0.08;
  let widened = false;
  if (currentPrice < lo) {
    lo = currentPrice - margin;
    widened = true;
  } else if (currentPrice > hi) {
    hi = currentPrice + margin;
    widened = true;
  }

  const span = hi - lo || 1;
  const pos = (price: number) => clamp(((price - lo) / span) * 100, 0, 100);

  // 판정은 게이지 좌표가 아니라 가격으로 한다 — 눈금을 넓혀도 결과가 바뀌면 안 된다.
  let triggered: "stop" | "take" | null = null;
  if (stopPrice !== null && currentPrice <= stopPrice) triggered = "stop";
  else if (takePrice !== null && currentPrice >= takePrice) triggered = "take";

  return {
    lo,
    hi,
    currentPos: pos(currentPrice),
    avgPos: pos(avgPrice),
    stopPos: stopPrice === null ? null : pos(stopPrice),
    takePos: takePrice === null ? null : pos(takePrice),
    triggered,
    widened,
  };
}

/** 매도벽 입력값 검증 (SPEC §6.2 유효성). 문제가 없으면 null. */
export function validateSellRule(
  stopPct: number | null,
  takePct: number | null
): string | null {
  if (stopPct === null && takePct === null) {
    return "둘 중 하나는 정해야 자동으로 팔 수 있습니다.";
  }
  if (stopPct !== null && !(stopPct > -100 && stopPct < 0)) {
    return "떨어지면 팔 기준은 -100%보다 크고 0%보다 작아야 합니다.";
  }
  if (takePct !== null && !(takePct > 0 && takePct <= 900)) {
    return "오르면 팔 기준은 0%보다 크고 900% 이하여야 합니다.";
  }
  return null;
}

/** 발동 시 손에 들어올 금액을 미리 알려주기 위한 라벨 축(전문용어 금지, SPEC §8.2). */
export const STOP_LABEL = "이만큼 떨어지면 팔기";
export const TAKE_LABEL = "이만큼 오르면 팔기";

/** 시장 종류별 통화 — 캐릭터는 한 통화만 쓴다(SPEC §2.1). */
export function currencyOf(kind: AccountKind): Currency {
  return kind === "US" ? "USD" : "KRW";
}
