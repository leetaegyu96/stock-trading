import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { CharacterCard } from "./CharacterCard";
import type { CardSummary } from "../types";

function makeCard(overrides: Partial<CardSummary>): CardSummary {
  return {
    name: "테스터",
    base_currency: "KRW",
    markets: ["KR"],
    benchmark_delta: null,
    benchmark_available: false,
    total_asset_krw: 1_000_000,
    twr: 0.05,
    pnl_krw: 50_000,
    today_pnl_pct: 0.01,
    equity_spark: [1, 2, 3],
    n_positions: 2,
    cash_krw: 100_000,
    ...overrides,
  };
}

describe("CharacterCard benchmark display (P0-3)", () => {
  it("does not silently hide a failed benchmark aggregation", () => {
    const html = renderToStaticMarkup(<CharacterCard summary={makeCard({ benchmark_available: false })} />);
    expect(html).toContain("벤치마크 미수집");
  });

  it("shows the delta when the benchmark is available", () => {
    const html = renderToStaticMarkup(
      <CharacterCard summary={makeCard({ benchmark_available: true, benchmark_delta: 0.03 })} />
    );
    expect(html).toContain("+3.00%p");
  });
});
