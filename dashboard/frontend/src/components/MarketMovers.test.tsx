import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { MarketMovers } from "./MarketMovers";
import type { Mover } from "../types";

function makeMover(overrides: Partial<Mover>): Mover {
  return {
    symbol: "005930",
    name: "삼성전자",
    market: "KR",
    change_pct: 0.012,
    close: 70000,
    ...overrides,
  };
}

describe("MarketMovers", () => {
  it("shows an empty state when there is no market data", () => {
    const html = renderToStaticMarkup(<MarketMovers movers={{}} />);
    expect(html).toContain("오늘 시장 데이터가 없습니다.");
  });

  it("renders a KR mover's close price with ₩ formatting", () => {
    const html = renderToStaticMarkup(
      <MarketMovers
        movers={{ KR: { up: [makeMover({ market: "KR", close: 70000 })], down: [] } }}
      />
    );
    expect(html).toContain("₩70,000");
  });

  it("renders a US mover's close price with $ formatting", () => {
    const html = renderToStaticMarkup(
      <MarketMovers
        movers={{
          US: { up: [makeMover({ symbol: "AAPL", name: "Apple", market: "US", close: 172.5 })], down: [] },
        }}
      />
    );
    expect(html).toContain("$172.50");
  });

  it("still renders the change percent alongside the price", () => {
    const html = renderToStaticMarkup(
      <MarketMovers
        movers={{ KR: { up: [makeMover({ change_pct: 0.0123 })], down: [] } }}
      />
    );
    expect(html).toContain("+1.23%");
  });
});
