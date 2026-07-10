// 운영 모드(PAPER)·데이터 as-of 표시용 순수 헬퍼. (audit §4/§5)
// 이 제품은 모의투자(페이퍼/리플레이) 전용이며 KIS는 시세 조회에만 쓰이고 실주문은
// 나가지 않는다 — 화면 어디서든 이 사실이 드러나야 한다.

export const OPERATING_MODE = "PAPER";
export const OPERATING_MODE_DESC =
  "모의투자(페이퍼) · KIS는 시세 조회 전용 · 실주문 없음";

/** WebSocket "연결" 여부와는 별개인 데이터 최신성(as-of) 표기.
 * 연결되어 있어도 마지막 스냅샷이 오래됐을 수 있고, 반대로 재연결 중에도
 * 마지막으로 받은 데이터의 시각은 알 수 있으므로 두 신호를 섞지 않는다. */
export function formatAsOf(ts: Date | null): string {
  if (ts === null || Number.isNaN(ts.getTime())) return "데이터 기준 시각 없음";
  return `데이터 기준 ${ts.toLocaleTimeString("ko-KR", { hour12: false })}`;
}
