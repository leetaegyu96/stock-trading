// 경량 인라인 SVG 스파크라인(영역+선). 컨테이너 폭을 가득 채우되
// vector-effect: non-scaling-stroke 로 선 두께는 왜곡 없이 유지한다.
import { useId } from "react";

export interface SparklineProps {
  points: number[];
  height?: number;
  /** 상승/하락 여부에 따라 선 색을 다르게 하고 싶을 때. 미지정 시 추세로 자동. */
  stroke?: string;
  className?: string;
}

const VIEW_W = 100; // 정규화 좌표계 (실제 폭은 CSS 100%)

export function Sparkline({ points, height = 52, stroke, className }: SparklineProps) {
  const gradId = useId().replace(/:/g, "");
  if (points.length === 0) {
    return <svg width="100%" height={height} className={className} aria-hidden="true" />;
  }

  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const padY = 3;
  const viewH = 30;
  const drawH = viewH - padY * 2;

  const stepX = points.length > 1 ? VIEW_W / (points.length - 1) : 0;
  const coords = points.map((p, i) => {
    const x = points.length > 1 ? i * stepX : VIEW_W / 2;
    const y = padY + drawH - ((p - min) / span) * drawH;
    return [x, y] as const;
  });

  const line = coords
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`)
    .join(" ");
  const area = `${line} L${VIEW_W},${viewH} L0,${viewH} Z`;

  const isUp = points[points.length - 1] >= points[0];
  const color = stroke ?? (isUp ? "var(--color-up)" : "var(--color-down)");

  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${viewH}`}
      width="100%"
      height={height}
      preserveAspectRatio="none"
      className={className}
      role="img"
      aria-label="최근 30일 자산 추이"
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.22" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradId})`} stroke="none" />
      <path
        d={line}
        fill="none"
        stroke={color}
        strokeWidth="1.8"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

export default Sparkline;
