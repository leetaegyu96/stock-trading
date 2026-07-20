import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { HoldingsPreview } from "./HoldingsPreview";
import type { CharPortfolio, HoldingRank } from "../types";

function makeRank(overrides: Partial<HoldingRank>): HoldingRank {
  return {
    symbol: "005930",
    name: "삼성전자",
    market: "KR",
    close: 73500,
    pnl_pct: 0.08,
    ...overrides,
  };
}

function makeChar(overrides: Partial<CharPortfolio>): CharPortfolio {
  return {
    name: "국내형",
    today_pnl_pct: 0.01,
    n_positions: 1,
    best: makeRank({}),
    worst: null,
    ...overrides,
  };
}

describe("HoldingsPreview", () => {
  it("shows an empty state when there are no characters", () => {
    const html = renderToStaticMarkup(<HoldingsPreview characters={[]} />);
    expect(html).toContain("아직 보유 데이터가 없습니다.");
  });

  it("renders a KR best item's price with ₩ formatting", () => {
    const html = renderToStaticMarkup(
      <HoldingsPreview characters={[makeChar({ best: makeRank({ market: "KR", close: 73500 }) })]} />
    );
    expect(html).toContain("₩73,500");
  });

  it("renders a US worst item's price with $ formatting", () => {
    const html = renderToStaticMarkup(
      <HoldingsPreview
        characters={[
          makeChar({
            best: null,
            worst: makeRank({ symbol: "AAPL", name: "Apple", market: "US", close: 172.5, pnl_pct: -0.03 }),
          }),
        ]}
      />
    );
    expect(html).toContain("$172.50");
  });

  it("still renders the pnl percent alongside the price", () => {
    const html = renderToStaticMarkup(
      <HoldingsPreview characters={[makeChar({ best: makeRank({ pnl_pct: 0.0812 }) })]} />
    );
    expect(html).toContain("+8.12%");
  });

  it("shows — when a rank is absent (no price rendered)", () => {
    const html = renderToStaticMarkup(<HoldingsPreview characters={[makeChar({ best: null })]} />);
    expect(html).toContain("—");
  });
});
