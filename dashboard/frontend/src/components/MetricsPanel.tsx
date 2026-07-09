// 상세 페이지 성과지표 스트립: TWR·MDD·누적손익·거래수·승률.
// 값이 주인공(크고 진하게), 라벨은 보조. 비율(ratio) → % 변환은 표기 직전 1회.
import type { Metrics } from "../types";
import { formatSignedKrw, signClass, signedPct } from "./format";

export interface MetricsPanelProps {
  metrics: Metrics;
  className?: string;
}

export function MetricsPanel({ metrics, className }: MetricsPanelProps) {
  const twrPct = metrics.twr * 100;
  const mddPct = metrics.mdd * 100;
  const winRatePct = metrics.win_rate * 100;

  const items: { label: string; value: string; cls?: string }[] = [
    { label: "수익률 (TWR)", value: signedPct(twrPct), cls: signClass(twrPct) },
    { label: "최대 낙폭 (MDD)", value: signedPct(mddPct), cls: signClass(mddPct) },
    { label: "누적손익", value: formatSignedKrw(metrics.pnl_krw), cls: signClass(metrics.pnl_krw) },
    { label: "거래 횟수", value: `${metrics.n_trades.toLocaleString("ko-KR")}건` },
    { label: "승률", value: `${winRatePct.toFixed(1)}%` },
  ];

  return (
    <div className={className}>
      <div className="metrics-strip">
        {items.map((it) => (
          <div key={it.label} className="metrics-strip__item">
            <span className="metrics-strip__label">{it.label}</span>
            <span className={`metrics-strip__value num ${it.cls ?? ""}`}>{it.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default MetricsPanel;
