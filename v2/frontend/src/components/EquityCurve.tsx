// 자산곡선. 원금선(수평 점선) 대비 현재 위치가 한눈에 보이게 그린다(SPEC §8.3).
import type { Currency, EquityPoint } from "../types";
import { compactMoney, formatMoney, signClass, signedPct } from "./format";

export interface EquityCurveProps {
  points: EquityPoint[];
  /** 원금(수익률 분모) — 점선으로 그린다 */
  seed: number;
  currency: Currency;
  height?: number;
}

const W = 600;
const PAD_L = 8;
const PAD_R = 60;
const PAD_T = 10;
const PAD_B = 18;

export function EquityCurve({ points, seed, currency, height = 200 }: EquityCurveProps) {
  if (points.length === 0) {
    return <p className="muted small">아직 자산 기록이 없습니다. 첫 거래를 하면 쌓이기 시작합니다.</p>;
  }

  const values = points.map((p) => p.equity);
  // 원금선이 화면 밖으로 나가면 "원금 대비" 비교가 불가능하므로 범위에 반드시 포함한다.
  const min = Math.min(...values, seed);
  const max = Math.max(...values, seed);
  const span = max - min || Math.abs(max) || 1;
  const lo = min - span * 0.08;
  const hi = max + span * 0.08;

  const plotW = W - PAD_L - PAD_R;
  const plotH = height - PAD_T - PAD_B;
  const x = (i: number) => PAD_L + (points.length > 1 ? (i * plotW) / (points.length - 1) : plotW / 2);
  const y = (v: number) => PAD_T + plotH - ((v - lo) / (hi - lo)) * plotH;

  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.equity).toFixed(1)}`).join(" ");
  const last = values[values.length - 1];
  const pnl = last - seed;
  const pct = seed > 0 ? (last / seed - 1) * 100 : 0;
  const color = pnl >= 0 ? "var(--color-up)" : "var(--color-down)";

  return (
    <div className="chart">
      <svg
        className="chart__svg"
        viewBox={`0 0 ${W} ${height}`}
        role="img"
        aria-label={`자산 추이. 원금 ${formatMoney(seed, currency)} 대비 현재 ${formatMoney(last, currency)}`}
      >
        <defs>
          <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.18" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>

        <path d={`${line} L${x(points.length - 1)},${PAD_T + plotH} L${PAD_L},${PAD_T + plotH} Z`} fill="url(#eqFill)" />
        <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />

        {/* 원금선 */}
        <line
          x1={PAD_L}
          x2={W - PAD_R}
          y1={y(seed)}
          y2={y(seed)}
          stroke="var(--chart-hairline)"
          strokeWidth="1"
          strokeDasharray="4 4"
        />
        <text x={W - PAD_R + 6} y={y(seed) + 3.5} fontSize="10" fill="var(--color-text-muted)">
          처음 넣은 돈
        </text>
        <text
          x={W - PAD_R + 6}
          y={y(last) + 3.5}
          fontSize="10"
          fill="var(--color-text-sub)"
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {compactMoney(last, currency)}
        </text>

        <text x={PAD_L} y={height - 4} fontSize="10" fill="var(--color-text-muted)">
          {points[0].ts.slice(5, 10)}
        </text>
        <text x={W - PAD_R} y={height - 4} fontSize="10" fill="var(--color-text-muted)" textAnchor="end">
          {points[points.length - 1].ts.slice(5, 10)}
        </text>
      </svg>

      <p className="small">
        처음 넣은 돈 {formatMoney(seed, currency)} → 지금 {formatMoney(last, currency)}{" "}
        <span className={signClass(pnl)}>
          ({pnl >= 0 ? "+" : "-"}
          {formatMoney(Math.abs(pnl), currency)}, {signedPct(pct, 1)})
        </span>
      </p>
    </div>
  );
}

export default EquityCurve;
