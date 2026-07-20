// 상세 페이지 자산곡선 차트 (인라인 SVG, 외부 라이브러리 없음).
// - ResizeObserver 로 컨테이너 실측 폭에 픽셀 단위로 그려 비율 왜곡이 없다.
// - Y축 눈금(억/만 축약) + 수평 그리드, X축 날짜 눈금, 기간 시작값 기준선(점선).
// - 크로스헤어 + 툴팁: 포인터의 X에 가장 가까운 데이터로 스냅.
// - 기간 토글(1M/3M/6M/전체). 선 색은 기간 수익 부호(상승=빨강/하락=파랑).
import { useEffect, useMemo, useRef, useState } from "react";
import type { EquityPoint } from "../types";
import { changeArrow, formatKrw, formatKrwCompact, shortDate, signClass, signedPct } from "./format";

/** 구간 수익률 칩 툴팁 — 시간가중수익률(TWR) 기준임을 명시(입출금 왜곡 제거). */
const TWR_TOOLTIP = "TWR(시간가중수익률) 기준 — 입출금으로 인한 왜곡을 제외한 선택 기간 수익률";

export interface EquityChartProps {
  points: EquityPoint[];
  /** 벤치마크 오버레이 자리(후속) — 현재 미사용. */
  benchmarkPoints?: EquityPoint[];
  height?: number;
  className?: string;
}

type Period = "1M" | "3M" | "6M" | "ALL";

const PERIOD_LABEL: Record<Period, string> = {
  "1M": "1개월",
  "3M": "3개월",
  "6M": "6개월",
  ALL: "전체",
};

const PERIOD_DAYS: Record<Exclude<Period, "ALL">, number> = {
  "1M": 30,
  "3M": 90,
  "6M": 180,
};

const MARGIN = { top: 14, right: 14, bottom: 26, left: 56 };

function filterByPeriod(points: EquityPoint[], period: Period): EquityPoint[] {
  if (period === "ALL" || points.length === 0) return points;
  const lastTs = new Date(points[points.length - 1].ts).getTime();
  if (Number.isNaN(lastTs)) return points;
  const cutoff = lastTs - PERIOD_DAYS[period] * 24 * 60 * 60 * 1000;
  const filtered = points.filter((p) => {
    const t = new Date(p.ts).getTime();
    return Number.isNaN(t) ? true : t >= cutoff;
  });
  return filtered.length > 1 ? filtered : points;
}

/** 사람이 읽기 좋은 "nice" 눈금 값들. */
function niceTicks(min: number, max: number, target = 4): number[] {
  const span = max - min;
  if (span <= 0) return [min];
  const step0 = span / target;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const norm = step0 / mag;
  const step = mag * (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10);
  const ticks: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) {
    ticks.push(v);
  }
  return ticks;
}

function tickDate(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function EquityChart({ points, height = 260, className }: EquityChartProps) {
  const [period, setPeriod] = useState<Period>("3M");
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);

  // 컨테이너 실측 폭 추적 — SVG 를 픽셀 단위로 그려 비율 왜곡 방지.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      setWidth(Math.max(0, Math.floor(w)));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const visible = useMemo(() => filterByPeriod(points, period), [points, period]);

  const geom = useMemo(() => {
    if (visible.length === 0 || width <= MARGIN.left + MARGIN.right) return null;
    const plotW = width - MARGIN.left - MARGIN.right;
    const plotH = height - MARGIN.top - MARGIN.bottom;
    const values = visible.map((p) => p.equity_krw);
    const first = values[0];
    let lo = Math.min(...values, first);
    let hi = Math.max(...values, first);
    const pad = (hi - lo || Math.abs(hi) * 0.01 || 1) * 0.06;
    lo -= pad;
    hi += pad;
    const x = (i: number) =>
      MARGIN.left + (visible.length > 1 ? (i / (visible.length - 1)) * plotW : plotW / 2);
    const y = (v: number) => MARGIN.top + plotH - ((v - lo) / (hi - lo)) * plotH;
    const coords = visible.map((p, i) => [x(i), y(p.equity_krw)] as const);
    const line = coords
      .map(([cx, cy], i) => `${i === 0 ? "M" : "L"}${cx.toFixed(1)},${cy.toFixed(1)}`)
      .join(" ");
    const bottom = MARGIN.top + plotH;
    const area = `${line} L${coords[coords.length - 1][0].toFixed(1)},${bottom} L${coords[0][0].toFixed(1)},${bottom} Z`;
    // X축 날짜 눈금 ~5개 (양끝 포함)
    const tickCount = Math.min(5, visible.length);
    const xTicks = Array.from({ length: tickCount }, (_, k) =>
      Math.round((k / (tickCount - 1 || 1)) * (visible.length - 1))
    );
    return {
      plotW, plotH, lo, hi, x, y, coords, line, area, bottom,
      yTicks: niceTicks(lo, hi),
      xTicks: [...new Set(xTicks)],
      baselineY: y(first),
    };
  }, [visible, width, height]);

  if (points.length === 0) {
    return (
      <div className={className}>
        <div className="equity-chart__head">
          <PeriodToggle period={period} onChange={setPeriod} />
        </div>
        <div className="detail-panel__state">자산곡선 데이터가 없습니다.</div>
      </div>
    );
  }

  const first = visible[0];
  const last = visible[visible.length - 1];
  const changePct =
    first.equity_krw !== 0
      ? ((last.equity_krw - first.equity_krw) / first.equity_krw) * 100
      : 0;
  const trend = signClass(changePct);
  const color = `var(--color-${trend === "neutral" ? "neutral" : trend})`;

  const hover = hoverIdx !== null && geom ? { idx: hoverIdx, p: visible[hoverIdx] } : null;
  const hoverChangePct =
    hover && first.equity_krw !== 0
      ? ((hover.p.equity_krw - first.equity_krw) / first.equity_krw) * 100
      : null;

  const handleMove = (e: React.PointerEvent<SVGRectElement>) => {
    if (!geom || visible.length === 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const ratio = geom.plotW > 0 ? px / geom.plotW : 0;
    const idx = Math.round(ratio * (visible.length - 1));
    setHoverIdx(Math.max(0, Math.min(visible.length - 1, idx)));
  };

  // 툴팁 위치: 오른쪽 가장자리에서 좌측으로 반전
  const tooltipLeft =
    hover && geom
      ? Math.min(Math.max(geom.coords[hover.idx][0] + 12, MARGIN.left), width - 190)
      : 0;

  return (
    <div className={className}>
      <div className="equity-chart__head">
        <div className="equity-chart__summary">
          <strong className="num">{formatKrw(last.equity_krw)}</strong>
          <span className="equity-chart__period-label">선택 기간 수익률</span>
          <span className={`chip chip--${trend}`} title={TWR_TOOLTIP}>
            <span aria-hidden="true">{changeArrow(changePct)}</span> {signedPct(changePct)}
          </span>
          <span className="equity-chart__range">
            {shortDate(first.ts)} – {shortDate(last.ts)}
          </span>
        </div>
        <PeriodToggle period={period} onChange={setPeriod} />
      </div>

      <div className="equity-chart__plot" ref={wrapRef} style={{ height }}>
        {geom && (
          <>
            <svg width={width} height={height} role="img" aria-label="자산곡선 차트">
              <defs>
                <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity="0.16" />
                  <stop offset="100%" stopColor={color} stopOpacity="0" />
                </linearGradient>
              </defs>

              {/* 수평 그리드 + Y축 라벨 */}
              {geom.yTicks.map((v) => (
                <g key={v}>
                  <line
                    x1={MARGIN.left} x2={width - MARGIN.right}
                    y1={geom.y(v)} y2={geom.y(v)}
                    stroke="var(--chart-grid)" strokeWidth="1"
                  />
                  <text
                    x={MARGIN.left - 8} y={geom.y(v) + 3.5}
                    textAnchor="end" fontSize="11"
                    fill="var(--color-text-muted)" className="num"
                  >
                    {formatKrwCompact(v)}
                  </text>
                </g>
              ))}

              {/* 기간 시작값 기준선 */}
              <line
                x1={MARGIN.left} x2={width - MARGIN.right}
                y1={geom.baselineY} y2={geom.baselineY}
                stroke="var(--chart-hairline)" strokeWidth="1"
                strokeDasharray="3 4" opacity="0.7"
              />

              {/* X축 날짜 라벨 */}
              {geom.xTicks.map((i) => (
                <text
                  key={i}
                  x={geom.x(i)} y={height - 8}
                  textAnchor="middle" fontSize="11"
                  fill="var(--color-text-muted)" className="num"
                >
                  {tickDate(visible[i].ts)}
                </text>
              ))}

              {/* 영역 + 선 */}
              <path d={geom.area} fill="url(#eqGrad)" stroke="none" />
              <path
                d={geom.line} fill="none" stroke={color}
                strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
              />

              {/* 크로스헤어 */}
              {hover && (
                <g>
                  <line
                    x1={geom.coords[hover.idx][0]} x2={geom.coords[hover.idx][0]}
                    y1={MARGIN.top} y2={geom.bottom}
                    stroke="var(--chart-hairline)" strokeWidth="1"
                  />
                  <circle
                    cx={geom.coords[hover.idx][0]} cy={geom.coords[hover.idx][1]}
                    r="4" fill={color} stroke="var(--color-surface)" strokeWidth="2"
                  />
                </g>
              )}

              {/* 포인터 히트 영역 (플롯 전체) */}
              <rect
                x={MARGIN.left} y={MARGIN.top}
                width={geom.plotW} height={geom.plotH}
                fill="transparent"
                onPointerMove={handleMove}
                onPointerLeave={() => setHoverIdx(null)}
              />
            </svg>

            {hover && hoverChangePct !== null && (
              <div className="equity-chart__tooltip" style={{ left: tooltipLeft }}>
                <div className="equity-chart__tooltip-date">{shortDate(hover.p.ts)}</div>
                <div className="equity-chart__tooltip-value num">
                  {formatKrw(hover.p.equity_krw)}
                </div>
                <div className={`equity-chart__tooltip-change num ${signClass(hoverChangePct)}`}>
                  기간 시작 대비 {signedPct(hoverChangePct)}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function PeriodToggle({
  period,
  onChange,
}: {
  period: Period;
  onChange: (p: Period) => void;
}) {
  const periods: Period[] = ["1M", "3M", "6M", "ALL"];
  return (
    <div className="seg" role="group" aria-label="기간 선택">
      {periods.map((p) => (
        <button
          key={p}
          type="button"
          className={`seg__btn${p === period ? " is-active" : ""}`}
          onClick={() => onChange(p)}
        >
          {PERIOD_LABEL[p]}
        </button>
      ))}
    </div>
  );
}

export default EquityChart;
