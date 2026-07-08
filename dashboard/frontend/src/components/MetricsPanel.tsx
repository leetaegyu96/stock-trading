// 상세 페이지 성과지표 패널: TWR·MDD·누적손익·거래수·승률.
// Metrics의 twr/mdd/win_rate는 백엔드 관례상 비율(ratio)로 내려오므로 표기 직전 *100.
import type { Metrics } from "../types";
import { formatKrw, signClass, signedPct } from "./format";

export interface MetricsPanelProps {
  metrics: Metrics;
  className?: string;
}

export function MetricsPanel({ metrics, className }: MetricsPanelProps) {
  const twrPct = metrics.twr * 100;
  const mddPct = metrics.mdd * 100;
  const winRatePct = metrics.win_rate * 100;
  const pnlSign = signClass(metrics.pnl_krw);

  return (
    <div className={className}>
      <div className="metrics-panel__grid">
        <div className="metrics-panel__item">
          <span className="metrics-panel__label">TWR</span>
          <span className={`metrics-panel__value ${signClass(twrPct)}`}>{signedPct(twrPct)}</span>
        </div>
        <div className="metrics-panel__item">
          <span className="metrics-panel__label">MDD</span>
          <span className={`metrics-panel__value ${signClass(mddPct)}`}>{signedPct(mddPct)}</span>
        </div>
        <div className="metrics-panel__item">
          <span className="metrics-panel__label">누적손익</span>
          <span className={`metrics-panel__value ${pnlSign}`}>{formatKrw(metrics.pnl_krw)}</span>
        </div>
        <div className="metrics-panel__item">
          <span className="metrics-panel__label">거래수</span>
          <span className="metrics-panel__value">{metrics.n_trades.toLocaleString("ko-KR")}건</span>
        </div>
        <div className="metrics-panel__item">
          <span className="metrics-panel__label">승률</span>
          <span className="metrics-panel__value">{winRatePct.toFixed(1)}%</span>
        </div>
      </div>
    </div>
  );
}

export default MetricsPanel;
