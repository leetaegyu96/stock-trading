import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ModeBar } from "./ModeBar";

describe("ModeBar (audit §4/§5)", () => {
  it("always shows the PAPER operating-mode badge", () => {
    const html = renderToStaticMarkup(<ModeBar connected={true} asOf={new Date("2026-07-10T05:00:00Z")} markets={["KR", "US"]} />);
    expect(html).toContain("PAPER");
  });

  it("shows data as-of distinct from the WebSocket connection status", () => {
    const ts = new Date("2026-07-10T05:00:00Z");
    const connectedHtml = renderToStaticMarkup(<ModeBar connected={true} asOf={ts} markets={["KR"]} />);
    const disconnectedHtml = renderToStaticMarkup(<ModeBar connected={false} asOf={ts} markets={["KR"]} />);
    // as-of text is identical regardless of connection state — freshness != connection.
    expect(connectedHtml).toContain("데이터 기준");
    expect(disconnectedHtml).toContain("데이터 기준");
    expect(connectedHtml).toContain("실시간 연결");
    expect(disconnectedHtml).toContain("연결 끊김");
  });

  it("still shows PAPER and an as-of state even with no snapshot yet", () => {
    const html = renderToStaticMarkup(<ModeBar connected={false} asOf={null} markets={[]} />);
    expect(html).toContain("PAPER");
    expect(html).toContain("데이터 기준 시각 없음");
  });
});

describe("ModeBar per-market data as-of (P0)", () => {
  const twoMarkets = [
    { market: "KR", last_close_date: "2026-07-10", last_open_date: "2026-07-10" },
    { market: "US", last_close_date: "2026-07-09", last_open_date: "2026-07-09" },
  ];

  it("renders both markets' as-of dates", () => {
    const html = renderToStaticMarkup(
      <ModeBar connected={true} asOf={new Date("2026-07-10T05:00:00Z")} markets={["KR", "US"]} initialMarketStatuses={twoMarkets} />
    );
    expect(html).toContain("KR 데이터기준 2026-07-10");
    expect(html).toContain("US 데이터기준 2026-07-09");
  });

  it("renders — for a market with no close date yet", () => {
    const html = renderToStaticMarkup(
      <ModeBar connected={true} asOf={null} markets={["KR"]} initialMarketStatuses={[{ market: "KR", last_close_date: null, last_open_date: null }]} />
    );
    expect(html).toContain("KR 데이터기준 —");
  });

  it("keeps connection state independent of per-market as-of rendering", () => {
    const connectedHtml = renderToStaticMarkup(
      <ModeBar connected={true} asOf={null} markets={["KR", "US"]} initialMarketStatuses={twoMarkets} />
    );
    const disconnectedHtml = renderToStaticMarkup(
      <ModeBar connected={false} asOf={null} markets={["KR", "US"]} initialMarketStatuses={twoMarkets} />
    );
    for (const html of [connectedHtml, disconnectedHtml]) {
      expect(html).toContain("KR 데이터기준 2026-07-10");
      expect(html).toContain("US 데이터기준 2026-07-09");
    }
    expect(connectedHtml).toContain("실시간 연결");
    expect(disconnectedHtml).toContain("연결 끊김");
  });
});
