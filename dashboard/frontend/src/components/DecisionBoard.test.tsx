import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { DecisionBoard } from "./DecisionBoard";
import type { CardSummary, Dashboard } from "../types";

function makeCard(overrides: Partial<CardSummary> = {}): CardSummary {
  return {
    name: "국내형",
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

function makeBoard(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    movers: { KR: { up: [], down: [] } },
    characters: [],
    recent_trades: [],
    today_actions: [],
    risk: [],
    ...overrides,
  };
}

describe("DecisionBoard section order", () => {
  it("orders 오늘의 행동 → 포트폴리오 위험 → 캐릭터 카드 → 시장/최근체결", () => {
    const html = renderToStaticMarkup(
      <DecisionBoard cards={[makeCard({})]} board={makeBoard({})} boardError={null} />
    );
    const idxActions = html.indexOf('data-section="today-actions"');
    const idxRisk = html.indexOf('data-section="risk-strip"');
    const idxCards = html.indexOf('data-section="character-cards"');
    const idxMovers = html.indexOf('data-section="market-movers"');
    const idxRecent = html.indexOf('data-section="recent-trades"');

    expect(idxActions).toBeGreaterThanOrEqual(0);
    expect(idxRisk).toBeGreaterThan(idxActions);
    expect(idxCards).toBeGreaterThan(idxRisk);
    expect(idxMovers).toBeGreaterThan(idxCards);
    expect(idxRecent).toBeGreaterThan(idxMovers);
  });

  it('shows "오늘 예정된 행동 없음" when today_actions is empty', () => {
    const html = renderToStaticMarkup(
      <DecisionBoard cards={[makeCard({})]} board={makeBoard({ today_actions: [] })} boardError={null} />
    );
    expect(html).toContain("오늘 예정된 행동 없음");
  });

  it("falls back to a loading/error message per section while board is not yet loaded", () => {
    const html = renderToStaticMarkup(
      <DecisionBoard cards={[makeCard({})]} board={null} boardError={null} />
    );
    expect(html).toContain("불러오는 중…");
  });
});
