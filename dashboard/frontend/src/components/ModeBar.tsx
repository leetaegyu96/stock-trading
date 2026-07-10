// 앱 셸 상단 운영모드 바: 모든 화면에서 항상 보인다(audit §4/§5).
// - 운영 모드(PAPER) 배지: 이 제품은 모의투자/리플레이 전용, KIS는 시세조회만, 실주문 없음.
// - 데이터 as-of: WebSocket "연결" 여부와 별개 신호. 연결돼 있어도 마지막 스냅샷이
//   오래됐을 수 있으므로 두 표시를 분리한다.
import { OPERATING_MODE, OPERATING_MODE_DESC, formatAsOf } from "./mode";
import "./theme.css";

export interface ModeBarProps {
  /** WebSocket 연결 여부. */
  connected: boolean;
  /** 마지막으로 데이터 스냅샷을 받은 시각(연결 여부와 무관). */
  asOf: Date | null;
  /** 현재 화면에 걸린 시장 목록(참고 표시용). */
  markets: string[];
}

export function ModeBar({ connected, asOf, markets }: ModeBarProps) {
  return (
    <div className="mode-bar">
      <span className="mode-bar__badge" title={OPERATING_MODE_DESC}>
        {OPERATING_MODE}
      </span>
      <span className="mode-bar__desc">{OPERATING_MODE_DESC}</span>
      {markets.length > 0 && <span className="mode-bar__markets">{markets.join(" · ")}</span>}
      <span className="mode-bar__asof">{formatAsOf(asOf)}</span>
      <span className={`mode-bar__conn${connected ? " mode-bar__conn--on" : ""}`}>
        {connected ? "실시간 연결" : "연결 끊김"}
      </span>
    </div>
  );
}

export default ModeBar;
