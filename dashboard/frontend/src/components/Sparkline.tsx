// 경량 인라인 SVG 스파크라인. 외부 차트 라이브러리 의존 없이 30일 자산곡선 등을
// 작은 추세선으로 그린다.
export interface SparklineProps {
  points: number[];
  width?: number;
  height?: number;
  /** 상승/하락 여부에 따라 선 색을 다르게 하고 싶을 때. 미지정 시 neutral 색. */
  stroke?: string;
  className?: string;
}

export function Sparkline({
  points,
  width = 120,
  height = 32,
  stroke,
  className,
}: SparklineProps) {
  if (points.length === 0) {
    return (
      <svg width={width} height={height} className={className} aria-hidden="true" />
    );
  }

  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1; // 전부 동일값이면 0 나눗셈 방지
  const padY = 2;
  const drawH = height - padY * 2;

  const stepX = points.length > 1 ? width / (points.length - 1) : 0;
  const coords = points.map((p, i) => {
    const x = points.length > 1 ? i * stepX : width / 2;
    const y = padY + drawH - ((p - min) / span) * drawH;
    return [x, y] as const;
  });

  const path = coords
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`)
    .join(" ");

  const last = coords[coords.length - 1];
  const first = points[0];
  const lastVal = points[points.length - 1];
  const isUp = lastVal >= first;
  const lineColor = stroke ?? (isUp ? "var(--color-up, #d32f2f)" : "var(--color-down, #1565c0)");

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={className}
      role="img"
      aria-label="30일 자산곡선 스파크라인"
    >
      <path d={path} fill="none" stroke={lineColor} strokeWidth="1.75" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="2" fill={lineColor} />
    </svg>
  );
}

export default Sparkline;
