// 52주 범위 안에서 현재가가 어디인지 보여주는 게이지(SPEC §4.2).
// 점수·추천이 아니라 "사실 제시"다 — 높다/낮다 판단은 쓰지 않는다.
import type { Currency } from "../types";
import { formatMoney } from "./format";

export interface RangeGaugeProps {
  low: number;
  high: number;
  current: number;
  currency: Currency;
  /** 끝값 라벨을 감출 때(표 안처럼 좁은 칸) */
  compact?: boolean;
}

/** 0~100(%) 위치. 범위가 뒤집혀 있거나 0 폭이면 50%(가운데)로 둔다. */
export function rangePosition(low: number, high: number, current: number): number {
  const span = high - low;
  if (!(span > 0)) return 50;
  return Math.min(100, Math.max(0, ((current - low) / span) * 100));
}

export function RangeGauge({ low, high, current, currency, compact = false }: RangeGaugeProps) {
  const pos = rangePosition(low, high, current);
  return (
    <div className="range">
      <div
        className="range__bar"
        role="img"
        aria-label={`52주 범위에서 현재가 위치 ${pos.toFixed(0)}퍼센트 지점`}
      >
        <span className="range__dot" style={{ left: `${pos}%` }} />
      </div>
      {!compact && (
        <div className="range__ends">
          <span>1년 최저 {formatMoney(low, currency)}</span>
          <span>1년 최고 {formatMoney(high, currency)}</span>
        </div>
      )}
    </div>
  );
}

export default RangeGauge;
