import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MetricsPanel } from "./MetricsPanel";
import type { Metrics } from "../types";

function makeMetrics(overrides: Partial<Metrics>): Metrics {
  return {
    twr: 0.12,
    mdd: -0.2345,
    n_trades: 10,
    win_rate: 0.6,
    pnl_krw: 100000,
    cagr: 0.1,
    volatility: 0.2,
    sharpe: 1.1,
    sortino: 1.4,
    calmar: 0.5,
    profit_factor: 2.0,
    avg_win: 1000,
    avg_loss: -500,
    win_loss_ratio: 2.0,
    expectancy: 300,
    max_consecutive_losses: 3,
    recovery_days: 12,
    benchmark_return: null,
    benchmark_delta: null,
    benchmark_name: "",
    benchmark_available: false,
    ...overrides,
  };
}

describe("MetricsPanel benchmark-first display (P0-3)", () => {
  it("shows a 벤치마크 미수집 warning when benchmark_available is false (not hidden)", () => {
    const html = renderToStaticMarkup(<MetricsPanel metrics={makeMetrics({ benchmark_available: false })} />);
    expect(html).toContain("벤치마크 미수집");
  });

  it("leads with the excess-return delta when benchmark_available is true", () => {
    const metrics = makeMetrics({
      benchmark_available: true,
      benchmark_return: 0.05,
      benchmark_delta: 0.07,
      benchmark_name: "KOSPI",
    });
    const html = renderToStaticMarkup(<MetricsPanel metrics={metrics} />);
    expect(html).toContain("초과수익");
    expect(html).toContain("+7.00%p");
  });

  it("never uses the word 검증됨", () => {
    const availableHtml = renderToStaticMarkup(
      <MetricsPanel metrics={makeMetrics({ benchmark_available: true, benchmark_return: 0.05, benchmark_delta: 0.07 })} />
    );
    const unavailableHtml = renderToStaticMarkup(<MetricsPanel metrics={makeMetrics({ benchmark_available: false })} />);
    expect(availableHtml).not.toContain("검증됨");
    expect(unavailableHtml).not.toContain("검증됨");
  });
});

describe("MetricsPanel MDD phrasing", () => {
  it("shows MDD as 최대 낙폭 X%", () => {
    const html = renderToStaticMarkup(<MetricsPanel metrics={makeMetrics({ mdd: -0.2345 })} />);
    expect(html).toContain("최대 낙폭");
    expect(html).toContain("23.45%");
  });
});

describe("MetricsPanel 승률 옆 평균이익·평균손실·손익비", () => {
  it("shows avg win/avg loss/손익비 alongside 승률", () => {
    const html = renderToStaticMarkup(
      <MetricsPanel metrics={makeMetrics({ win_rate: 0.6, avg_win: 12345, avg_loss: -6789, win_loss_ratio: 1.82 })} />
    );
    expect(html).toContain("승률");
    expect(html).toContain("60.0%");
    expect(html).toContain("평균이익");
    expect(html).toContain("+₩12,345");
    expect(html).toContain("평균손실");
    expect(html).toContain("-₩6,789");
    expect(html).toContain("손익비");
    expect(html).toContain("1.82");
  });
});

describe("MetricsPanel risk-adjusted strip", () => {
  it("renders Sharpe/Sortino/Calmar/Profit Factor/기대값/최대연속손실/회복기간", () => {
    const html = renderToStaticMarkup(<MetricsPanel metrics={makeMetrics({})} />);
    expect(html).toContain("Sharpe");
    expect(html).toContain("Sortino");
    expect(html).toContain("Calmar");
    expect(html).toContain("Profit Factor");
    expect(html).toContain("기대값");
    expect(html).toContain("최대연속손실");
    expect(html).toContain("회복기간");
  });
});
