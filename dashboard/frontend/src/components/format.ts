// 상세 페이지 전반에서 쓰는 숫자/날짜 포맷 헬퍼. 순수 함수라 테스트가 쉬움.

/** 원화 표기 (반올림 + 천단위 구분자). */
export function formatKrw(value: number): string {
  return `₩${Math.round(value).toLocaleString("ko-KR")}`;
}

/** 부호 있는 퍼센트 표기 (예: +1.23%, -0.50%). value는 이미 퍼센트 단위. */
export function signedPct(value: number, digits = 2): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

/** 부호에 따른 클래스명 (상승=up=빨강, 하락=down=파랑, 0=neutral). */
export function signClass(value: number): "up" | "down" | "neutral" {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "neutral";
}

/** YYYY-MM-DD(혹은 ISO) 문자열 기준, 오늘까지 보유일수(당일 포함 1일차). */
export function holdingDays(openedDate: string, now: Date = new Date()): number {
  const opened = new Date(openedDate);
  if (Number.isNaN(opened.getTime())) return 0;
  const msPerDay = 24 * 60 * 60 * 1000;
  const diff = Math.floor((now.getTime() - opened.getTime()) / msPerDay);
  return Math.max(0, diff) + 1;
}

/** fired 코드(G1, R3 ...)를 청신호(G*)/적신호(R*)로 분류. */
export type SignalKind = "green" | "red" | "unknown";

export function signalKind(code: string): SignalKind {
  if (code.startsWith("G")) return "green";
  if (code.startsWith("R")) return "red";
  return "unknown";
}

/** 매수/매도 side 한글 라벨. */
export function sideLabel(side: string): string {
  const upper = side.toUpperCase();
  if (upper.includes("BUY")) return "매수";
  if (upper.includes("SELL")) return "매도";
  return side;
}

/** 날짜 문자열을 YYYY-MM-DD 로 짧게 표기. 파싱 실패 시 원본 반환. */
export function shortDate(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toISOString().slice(0, 10);
}
