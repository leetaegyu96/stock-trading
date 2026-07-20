// 상세 페이지 성과지표: 1순위는 전략 vs 벤치마크 초과수익(P0-3) — 집계 실패면
// 경고 배지로 드러내고 조용히 숨기지 않는다. 그 아래 기본 지표 스트립(TWR·MDD·
// 누적손익·거래수·승률) + 위험조정 지표 스트립(Sharpe/Sortino/Calmar/PF/기대값/
// 최대연속손실/회복기간). 값이 주인공(크고 진하게), 라벨은 보조.
import type { Metrics } from "../types";
import {
  BENCHMARK_UNAVAILABLE_LABEL,
  benchmarkDeltaLabel,
  formatSignedKrw,
  mddLabel,
  signClass,
  signedPct,
} from "./format";

export interface MetricsPanelProps {
  metrics: Metrics;
  className?: string;
}

/** 위험조정 지표 각 값에 붙는 꼬리표(표본기간·거래수·비용·데이터버전).
 * 숫자 하나로 확신을 주지 않기 위한 최소한의 맥락 — 툴팁(title)으로 노출. */
function riskTooltip(metrics: Metrics): string {
  return `표본: 보유 거래이력 전체 · 거래수 ${metrics.n_trades.toLocaleString("ko-KR")}건 · 수수료·세금 포함 · 데이터: 리플레이/시드 스냅샷`;
}

function BenchmarkLead({ metrics }: { metrics: Metrics }) {
  if (!metrics.benchmark_available || metrics.benchmark_delta === null) {
    return (
      <div className="benchmark-lead">
        <span className="benchmark-lead__label">전략 vs 벤치마크</span>
        <span className="benchmark-lead__warn">⚠ {BENCHMARK_UNAVAILABLE_LABEL}</span>
      </div>
    );
  }
  const deltaPct = metrics.benchmark_delta * 100;
  return (
    <div className="benchmark-lead">
      <span className="benchmark-lead__label">전략 vs 벤치마크 초과수익</span>
      <strong className={`benchmark-lead__value num ${signClass(deltaPct)}`}>
        {benchmarkDeltaLabel(metrics.benchmark_delta)}
      </strong>
      {metrics.benchmark_name && (
        <span className="benchmark-lead__name">
          (전략 {signedPct(metrics.twr * 100)} vs {metrics.benchmark_name}{" "}
          {metrics.benchmark_return !== null ? signedPct(metrics.benchmark_return * 100) : "—"})
        </span>
      )}
    </div>
  );
}

export function MetricsPanel({ metrics, className }: MetricsPanelProps) {
  const twrPct = metrics.twr * 100;
  const winRatePct = metrics.win_rate * 100;

  const basicItems: { label: string; value: string; cls?: string }[] = [
    { label: "수익률 (TWR)", value: signedPct(twrPct), cls: signClass(twrPct) },
    { label: "최대 낙폭", value: mddLabel(metrics.mdd).replace("최대 낙폭 ", ""), cls: metrics.mdd < 0 ? "down" : "neutral" },
    { label: "누적손익", value: formatSignedKrw(metrics.pnl_krw), cls: signClass(metrics.pnl_krw) },
    { label: "거래 횟수", value: `${metrics.n_trades.toLocaleString("ko-KR")}건` },
    { label: "승률", value: `${winRatePct.toFixed(1)}%` },
    // 승률만으로는 맥락이 부족하므로 바로 옆에 평균이익·평균손실·손익비를 함께 보여준다.
    { label: "평균이익", value: formatSignedKrw(metrics.avg_win), cls: signClass(metrics.avg_win) },
    // avg_loss는 저장상 절대값(abs(losses.mean()), simcore/metrics.py:137)이므로 그대로
    // formatSignedKrw에 넣으면 "+₩..."로 이익처럼 보인다. 손실이므로 부호·색상을 뒤집어
    // "−₩..."(loss 색)로 표기한다. 0이면 부호 없이 중립.
    {
      label: "평균손실",
      value: formatSignedKrw(metrics.avg_loss > 0 ? -metrics.avg_loss : 0),
      cls: signClass(metrics.avg_loss > 0 ? -metrics.avg_loss : 0),
    },
    { label: "손익비", value: metrics.win_loss_ratio.toFixed(2) },
  ];

  const tooltip = riskTooltip(metrics);
  const riskItems: { label: string; value: string }[] = [
    { label: "Sharpe", value: metrics.sharpe.toFixed(2) },
    { label: "Sortino", value: metrics.sortino.toFixed(2) },
    { label: "Calmar", value: metrics.calmar.toFixed(2) },
    { label: "Profit Factor", value: metrics.profit_factor.toFixed(2) },
    { label: "기대값", value: formatSignedKrw(metrics.expectancy) },
    { label: "최대연속손실", value: `${metrics.max_consecutive_losses.toLocaleString("ko-KR")}회` },
    { label: "회복기간", value: `${metrics.recovery_days.toLocaleString("ko-KR")}일` },
  ];

  return (
    <div className={className}>
      <BenchmarkLead metrics={metrics} />
      <div className="metrics-strip">
        {basicItems.map((it) => (
          <div key={it.label} className="metrics-strip__item">
            <span className="metrics-strip__label">{it.label}</span>
            <span className={`metrics-strip__value num ${it.cls ?? ""}`}>{it.value}</span>
          </div>
        ))}
      </div>
      <div className="risk-strip">
        {riskItems.map((it) => (
          <div key={it.label} className="risk-strip__item" title={tooltip}>
            <span className="risk-strip__label">{it.label}</span>
            <span className="risk-strip__value num">{it.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default MetricsPanel;
