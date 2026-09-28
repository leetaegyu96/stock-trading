// 숫자·금액 포맷 헬퍼 (v1 dashboard/frontend/src/components/format.ts 에서 가져와
// v2 의 통화 규칙에 맞게 다듬음). 전부 순수 함수라 테스트가 쉽다.
//
// v2 원칙(SPEC §8.2): 금액은 천 단위 구분 + tabular-nums, 그리고 **숫자 옆에는 항상
// 의미를 붙인다** — "-320,000원" 이 아니라 "-320,000원 (-3.2%)".
import type { Currency } from "../types";

/** 통화별 소수 자릿수. KRW 는 원 단위(정수), USD 는 센트까지. */
function digitsFor(currency: Currency): number {
  return currency === "USD" ? 2 : 0;
}

/** 금액 표기: 1234567 → "1,234,567원", 310.66 → "$310.66". */
export function formatMoney(value: number, currency: Currency): string {
  const digits = digitsFor(currency);
  if (currency === "USD") {
    return `$${value.toLocaleString("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    })}`;
  }
  return `${Math.round(value).toLocaleString("ko-KR")}원`;
}

/** 부호를 앞에 붙인 금액: "+17,726원" / "-1,419원" / "0원". */
export function formatSignedMoney(value: number, currency: Currency): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${formatMoney(Math.abs(value), currency)}`;
}

/** 부호 있는 퍼센트: +1.23% / -0.50% / 0.00%. value 는 이미 퍼센트 단위. */
export function signedPct(value: number, digits = 2): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

/**
 * SPEC §8.2 의 핵심 표기 — 금액과 퍼센트를 늘 함께 보여준다.
 * 예: "-320,000원 (-3.2%)"
 */
export function moneyWithPct(value: number, pct: number, currency: Currency): string {
  return `${formatSignedMoney(value, currency)} (${signedPct(pct, 1)})`;
}

/** 부호에 따른 클래스명 — 한국 증권 관례: 상승=up=빨강, 하락=down=파랑. */
export function signClass(value: number): "up" | "down" | "neutral" {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "neutral";
}

/** 색만으로 등락을 구분하지 않기 위한 보조 기호(접근성). */
export function changeArrow(value: number): "▲" | "▼" | "–" {
  if (value > 0) return "▲";
  if (value < 0) return "▼";
  return "–";
}

/** 거래량 배수를 초보가 읽을 문장으로: 2.13 → "평소의 2.1배". */
export function volumeText(ratio: number): string {
  if (!Number.isFinite(ratio) || ratio <= 0) return "거래량 정보 없음";
  return `평소의 ${ratio.toFixed(1)}배`;
}

/** 큰 수를 짧게: 12,345,678 → "1,235만". 거래량·축 라벨용. */
export function compactNumber(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(abs / 1e8 >= 100 ? 0 : 2)}억`;
  if (abs >= 1e4) return `${sign}${Math.round(abs / 1e4).toLocaleString("ko-KR")}만`;
  return `${sign}${Math.round(abs).toLocaleString("ko-KR")}`;
}

/** 금액 축약(차트 축·요약): 124,328,302원 → "1.24억원". */
export function compactMoney(value: number, currency: Currency): string {
  if (currency === "USD") return `$${compactUsd(value)}`;
  return `${compactNumber(value)}원`;
}

function compactUsd(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
  return `${sign}${abs.toFixed(2)}`;
}

/** 매수/매도 한글 라벨. */
export function sideLabel(side: string): string {
  const upper = side.toUpperCase();
  if (upper === "BUY") return "매수";
  if (upper === "SELL") return "매도";
  return side;
}

/**
 * 체결 사유 → 초보용 라벨. SPEC §8.2: '손절'·'익절' 같은 전문용어를 쓰지 않는다.
 * kind 는 칩 색상 축(스타일 전용).
 */
export type ReasonKind = "manual" | "stop" | "take" | "unknown";

const REASON_MAP: Record<string, { label: string; kind: ReasonKind }> = {
  MANUAL: { label: "직접 주문", kind: "manual" },
  AUTO_STOP_LOSS: { label: "자동 매도 · 떨어져서 팔기", kind: "stop" },
  AUTO_TAKE_PROFIT: { label: "자동 매도 · 올라서 팔기", kind: "take" },
};

export function reasonInfo(reason: string): { label: string; kind: ReasonKind } {
  return REASON_MAP[reason.toUpperCase()] ?? { label: reason, kind: "unknown" };
}

/** 캐릭터(계좌) 종류 라벨. */
export function kindLabel(kind: string): string {
  if (kind === "KR") return "국내 주식";
  if (kind === "US") return "해외 주식";
  return kind;
}

/** 좁은 자리(뱃지·표 셀)용 짧은 라벨: "국내" / "해외". */
export function kindShort(kind: string): string {
  if (kind === "KR") return "국내";
  if (kind === "US") return "해외";
  return kind;
}

/** ISO 문자열 → YYYY-MM-DD. 파싱 실패 시 원본 반환. */
export function shortDate(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toISOString().slice(0, 10);
}

/** ISO 문자열 → "MM-DD HH:mm" (거래 내역용). */
export function shortDateTime(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
