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

/** 원화 축약 표기 (차트 축·요약용): 1.24억 / 8,240만 / 1,234원 단위. */
export function formatKrwCompact(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1e8) {
    const eok = abs / 1e8;
    return `${sign}${eok >= 100 ? Math.round(eok).toLocaleString("ko-KR") : eok.toFixed(2)}억`;
  }
  if (abs >= 1e4) return `${sign}${Math.round(abs / 1e4).toLocaleString("ko-KR")}만`;
  return `${sign}${Math.round(abs).toLocaleString("ko-KR")}`;
}

/** 부호 있는 원화 표기 (+₩1,234 / -₩1,234 / ₩0). */
export function formatSignedKrw(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}₩${Math.abs(Math.round(value)).toLocaleString("ko-KR")}`;
}

/** 거래 사유 enum → 한글 라벨 + 칩 톤. 미지의 값은 원문 그대로 중립 표기. */
export type ReasonKind = "buy" | "sell" | "stop" | "take" | "flow" | "unknown";

const REASON_MAP: Record<string, { label: string; kind: ReasonKind }> = {
  SIGNAL_BUY: { label: "신호 매수", kind: "buy" },
  SIGNAL_SELL: { label: "신호 매도", kind: "sell" },
  STOP_LOSS: { label: "손절", kind: "stop" },
  TAKE_PROFIT: { label: "익절", kind: "take" },
  TRAILING_STOP: { label: "트레일링 스탑(수익 보호)", kind: "take" },
  USER_WITHDRAWAL: { label: "출금 청산", kind: "flow" },
  DELISTED: { label: "상장폐지", kind: "flow" },
};

export function reasonInfo(reason: string): { label: string; kind: ReasonKind } {
  return REASON_MAP[reason.toUpperCase()] ?? { label: reason, kind: "unknown" };
}

/** 시장 통화 인지 가격 표기: KR → ₩(정수), US → $(소수 2자리). */
export function formatPrice(market: string, value: number): string {
  if (market.toUpperCase() === "US") {
    return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  return `₩${Math.round(value).toLocaleString("ko-KR")}`;
}

/** 별점(1~5)을 채워진/빈 별 문자열로 렌더. 범위를 벗어난 값은 0~max로 clamp. */
export function starString(stars: number, max = 5): string {
  const filled = Math.max(0, Math.min(max, Math.round(stars)));
  return "★".repeat(filled) + "☆".repeat(max - filled);
}

/** 부호 있는 시장 통화 표기 (실현손익용). */
export function formatSignedPrice(market: string, value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (market.toUpperCase() === "US") {
    return `${sign}$${abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  return `${sign}₩${Math.round(abs).toLocaleString("ko-KR")}`;
}
