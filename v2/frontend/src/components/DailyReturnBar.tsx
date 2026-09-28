// 일간 수익률 발산형 막대 — 0 을 가운데 두고 오름은 오른쪽(빨강), 내림은 왼쪽(파랑).
//
// 같은 표 안의 막대는 **보이는 값 중 절대값이 가장 큰 것**으로 정규화하므로 길이를
// 그대로 비교할 수 있다. 색만으로 방향을 말하지 않도록 값 텍스트(▲/▼ + 부호)를
// 반드시 옆에 함께 둔다 — 여기서는 aria-label 과 호출부의 숫자 셀이 그 역할을 한다.
import { signedPct } from "./format";
import { dailyBarGeometry } from "./ranking";

export interface DailyReturnBarProps {
  /** 일간 수익률 % */
  pct: number;
  /** 정규화 기준 — 같은 표에서 보이는 값들의 절대값 최대 */
  maxAbs: number;
  /** 스크린리더용 앞머리(예: "홍길동 오늘 수익률") */
  label?: string;
}

export function DailyReturnBar({ pct, maxAbs, label }: DailyReturnBarProps) {
  const { leftPct, widthPct, sign } = dailyBarGeometry(pct, maxAbs);
  const direction = pct > 0 ? "오름" : pct < 0 ? "내림" : "변화 없음";

  return (
    <div
      className="dbar"
      role="img"
      aria-label={`${label ? `${label} ` : ""}${signedPct(pct)} ${direction}`}
      data-testid="daily-bar"
      data-sign={sign}
    >
      <span className="dbar__zero" aria-hidden="true" />
      <span
        className={`dbar__fill dbar__fill--${sign}`}
        style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
        data-testid="daily-bar-fill"
        aria-hidden="true"
      />
    </div>
  );
}

export default DailyReturnBar;
