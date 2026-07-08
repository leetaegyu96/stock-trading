// 상세 페이지 자산곡선 차트. 외부 차트 라이브러리 없이 인라인 SVG로 그린다.
// 기간 토글(1개월/3개월/전체)을 지원하고, 벤치마크 오버레이는 후속 작업으로 남겨둔다
// (`benchmarkPoints` prop을 미리 받아두되 현재는 미사용 — 훅만 준비).
import { useMemo, useState } from "react";
import type { EquityPoint } from "../types";
import { formatKrw, shortDate, signClass } from "./format";

export interface EquityChartProps {
  points: EquityPoint[];
  /** 후속 작업(벤치마크 오버레이)을 위한 자리. 현재는 렌더링하지 않는다. */
  benchmarkPoints?: EquityPoint[];
  width?: number;
  height?: number;
  className?: string;
}

type Period = "1M" | "3M" | "ALL";

const PERIOD_LABEL: Record<Period, string> = {
  "1M": "1개월",
  "3M": "3개월",
  ALL: "전체",
};

const PERIOD_DAYS: Record<Exclude<Period, "ALL">, number> = {
  "1M": 30,
  "3M": 90,
};

function filterByPeriod(points: EquityPoint[], period: Period): EquityPoint[] {
  if (period === "ALL" || points.length === 0) return points;
  const lastTs = new Date(points[points.length - 1].ts).getTime();
  if (Number.isNaN(lastTs)) return points;
  const cutoff = lastTs - PERIOD_DAYS[period] * 24 * 60 * 60 * 1000;
  const filtered = points.filter((p) => {
    const t = new Date(p.ts).getTime();
    return Number.isNaN(t) ? true : t >= cutoff;
  });
  return filtered.length > 0 ? filtered : points;
}

export function EquityChart({
  points,
  width = 640,
  height = 220,
  className,
}: EquityChartProps) {
  const [period, setPeriod] = useState<Period>("3M");
  const visible = useMemo(() => filterByPeriod(points, period), [points, period]);

  if (points.length === 0) {
    return (
      <div className={className}>
        <ChartHeader period={period} onChange={setPeriod} />
        <div className="equity-chart__state">자산곡선 데이터가 없습니다.</div>
      </div>
    );
  }

  const padX = 8;
  const padY = 16;
  const drawW = width - padX * 2;
  const drawH = height - padY * 2;

  const values = visible.map((p) => p.equity_krw);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  const stepX = visible.length > 1 ? drawW / (visible.length - 1) : 0;
  const coords = visible.map((p, i) => {
    const x = padX + (visible.length > 1 ? i * stepX : drawW / 2);
    const y = padY + drawH - ((p.equity_krw - min) / span) * drawH;
    return [x, y] as const;
  });

  const linePath = coords
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`)
    .join(" ");
  const areaPath = `${linePath} L${coords[coords.length - 1][0].toFixed(2)},${(
    padY + drawH
  ).toFixed(2)} L${coords[0][0].toFixed(2)},${(padY + drawH).toFixed(2)} Z`;

  const first = visible[0];
  const last = visible[visible.length - 1];
  const changePct = first.equity_krw !== 0
    ? ((last.equity_krw - first.equity_krw) / first.equity_krw) * 100
    : 0;
  const trendClass = signClass(changePct);
  const lineColor = `var(--color-${trendClass === "neutral" ? "neutral" : trendClass})`;

  return (
    <div className={className}>
      <ChartHeader period={period} onChange={setPeriod} />
      <div className="equity-chart__summary">
        <span>{formatKrw(last.equity_krw)}</span>
        <span className={trendClass}>
          {changePct > 0 ? "+" : ""}
          {changePct.toFixed(2)}% ({shortDate(first.ts)} ~ {shortDate(last.ts)})
        </span>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        role="img"
        aria-label="자산곡선 차트"
      >
        <path d={areaPath} fill={lineColor} opacity="0.12" stroke="none" />
        <path
          d={linePath}
          fill="none"
          stroke={lineColor}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        <circle cx={coords[coords.length - 1][0]} cy={coords[coords.length - 1][1]} r="3" fill={lineColor} />
      </svg>
      <div className="equity-chart__axis">
        <span>{formatKrw(min)}</span>
        <span>{formatKrw(max)}</span>
      </div>
    </div>
  );
}

function ChartHeader({
  period,
  onChange,
}: {
  period: Period;
  onChange: (p: Period) => void;
}) {
  const periods: Period[] = ["1M", "3M", "ALL"];
  return (
    <div className="equity-chart__toggle" role="group" aria-label="기간 선택">
      {periods.map((p) => (
        <button
          key={p}
          type="button"
          className={`equity-chart__toggle-btn${p === period ? " is-active" : ""}`}
          onClick={() => onChange(p)}
        >
          {PERIOD_LABEL[p]}
        </button>
      ))}
    </div>
  );
}

export default EquityChart;
