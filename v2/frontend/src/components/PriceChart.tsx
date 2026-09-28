// 30일 가격 차트(선) + 거래량 막대. 외부 차트 라이브러리를 쓰지 않고 인라인 SVG 로
// 직접 그린다 — 색은 theme.css 토큰만 써서 라이트/다크 모두에서 읽히게 한다.
import { useState } from "react";
import type { Currency, DailyBar } from "../types";
import { compactNumber, formatMoney, signClass, signedPct } from "./format";

export interface PriceChartProps {
  bars: DailyBar[];
  currency: Currency;
  height?: number;
}

const W = 600;           // 내부 좌표계 폭 (실제 폭은 CSS 100%)
const PAD_L = 8;
const PAD_R = 54;        // 오른쪽 가격 축 라벨 자리
const PAD_T = 10;
const VOL_H = 34;        // 아래쪽 거래량 막대 높이
const AXIS_H = 16;       // 날짜 축 라벨 높이

export function PriceChart({ bars, currency, height = 240 }: PriceChartProps) {
  const [hover, setHover] = useState<number | null>(null);

  if (bars.length === 0) {
    return <p className="muted small">차트를 그릴 가격 데이터가 없습니다.</p>;
  }

  const H = height;
  const priceH = H - PAD_T - VOL_H - AXIS_H - 6;
  const closes = bars.map((b) => b.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || Math.abs(max) || 1;
  // 위아래로 6% 여유를 둬 선이 테두리에 붙지 않게 한다.
  const lo = min - span * 0.06;
  const hi = max + span * 0.06;

  const plotW = W - PAD_L - PAD_R;
  const x = (i: number) => PAD_L + (bars.length > 1 ? (i * plotW) / (bars.length - 1) : plotW / 2);
  const y = (v: number) => PAD_T + priceH - ((v - lo) / (hi - lo)) * priceH;

  const line = bars.map((b, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(b.close).toFixed(1)}`).join(" ");
  const area = `${line} L${x(bars.length - 1).toFixed(1)},${PAD_T + priceH} L${PAD_L},${PAD_T + priceH} Z`;

  const first = closes[0];
  const last = closes[closes.length - 1];
  const up = last >= first;
  const color = up ? "var(--color-up)" : "var(--color-down)";

  const volMax = Math.max(...bars.map((b) => b.volume), 1);
  const volTop = PAD_T + priceH + 6;
  const barW = Math.max(1.5, (plotW / bars.length) * 0.62);

  // 가격 축: 위·중간·아래 3칸이면 읽는 데 충분하다(격자 과밀 방지).
  const ticks = [hi, (hi + lo) / 2, lo];

  const hovered = hover === null ? null : bars[hover];
  const hoverPct = hovered && hover! > 0
    ? (hovered.close / bars[hover! - 1].close - 1) * 100
    : 0;

  return (
    <div className="chart">
      <svg
        className="chart__svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`최근 ${bars.length}거래일 가격 추이. ${bars[0].date}부터 ${bars[bars.length - 1].date}까지`}
        onMouseLeave={() => setHover(null)}
      >
        {/* 가로 격자 + 오른쪽 가격 라벨 */}
        {ticks.map((t, i) => (
          <g key={i}>
            <line
              x1={PAD_L}
              x2={W - PAD_R}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--chart-grid)"
              strokeWidth="1"
            />
            <text
              x={W - PAD_R + 6}
              y={y(t) + 3.5}
              fontSize="10"
              fill="var(--color-text-muted)"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {formatMoney(t, currency)}
            </text>
          </g>
        ))}

        <defs>
          <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.2" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#priceFill)" />
        <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />

        {/* 거래량 막대 — 가격과 같은 x 축을 공유한다 */}
        {bars.map((b, i) => {
          const h = Math.max(1, (b.volume / volMax) * VOL_H);
          return (
            <rect
              key={b.date}
              x={x(i) - barW / 2}
              y={volTop + (VOL_H - h)}
              width={barW}
              height={h}
              fill="var(--chart-hairline)"
              opacity={hover === i ? 0.95 : 0.45}
            />
          );
        })}

        {/* 날짜 축: 처음·중간·끝만 — 30개를 다 쓰면 읽히지 않는다 */}
        {[0, Math.floor((bars.length - 1) / 2), bars.length - 1].map((i) => (
          <text
            key={`d${i}`}
            x={x(i)}
            y={H - 3}
            fontSize="10"
            fill="var(--color-text-muted)"
            textAnchor={i === 0 ? "start" : i === bars.length - 1 ? "end" : "middle"}
          >
            {bars[i].date.slice(5)}
          </text>
        ))}

        {hovered && (
          <line
            x1={x(hover!)}
            x2={x(hover!)}
            y1={PAD_T}
            y2={volTop + VOL_H}
            stroke="var(--chart-hairline)"
            strokeDasharray="3 3"
          />
        )}
        {hovered && <circle cx={x(hover!)} cy={y(hovered.close)} r="3.5" fill={color} />}

        {/* 마우스를 받는 투명 판. 막대마다 rect 를 두는 편이 좌표 계산보다 안전하다. */}
        {bars.map((b, i) => (
          <rect
            key={`h${b.date}`}
            x={x(i) - plotW / bars.length / 2}
            y={0}
            width={plotW / bars.length}
            height={H}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </svg>

      {hovered && (
        <div
          className="chart__tip"
          style={{
            left: `${(x(hover!) / W) * 100}%`,
            top: 0,
            transform: hover! > bars.length / 2 ? "translateX(-105%)" : "translateX(8px)",
          }}
        >
          <div>{hovered.date}</div>
          <div>
            종가 {formatMoney(hovered.close, currency)}{" "}
            {hover! > 0 && <span className={signClass(hoverPct)}>{signedPct(hoverPct, 1)}</span>}
          </div>
          <div className="muted">거래량 {compactNumber(hovered.volume)}주</div>
        </div>
      )}

      <div className="chart__legend">
        <span>선 = 하루 종가</span>
        <span>아래 막대 = 그날 거래량</span>
      </div>
    </div>
  );
}

export default PriceChart;
