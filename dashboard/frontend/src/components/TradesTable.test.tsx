import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { TradesTable } from "./TradesTable";
import type { LifecycleOut, TradeOut } from "../types";

function makeTrade(overrides: Partial<TradeOut>): TradeOut {
  return {
    ts: "2026-07-01T00:00:00Z",
    date: "2026-07-01",
    symbol: "005930",
    name: "삼성전자",
    market: "KR",
    side: "SELL",
    quantity: 1,
    price: 1000,
    fee: 0,
    tax: 0,
    reason: "SIGNAL_SELL",
    green_count: 0,
    red_count: 1,
    green_score: 0,
    red_score: 10,
    fired: [],
    signal_summary: "",
    signal_detail: [],
    realized_pnl: -100,
    decision_type: "FULL_SELL",
    trigger_rule: "",
    ...overrides,
  };
}

describe("TradesTable signal labelling (P0-2)", () => {
  it("labels the signal axis 기술적 매수/매도 신호, not 청/적신호", () => {
    const html = renderToStaticMarkup(<TradesTable trades={[makeTrade({})]} />);
    expect(html).toContain("기술적 매수/매도 신호");
    expect(html).not.toContain("청신호");
    expect(html).not.toContain("적신호");
  });

  it("shows the news/disclosure/flow disclaimer near the signal display", () => {
    const html = renderToStaticMarkup(<TradesTable trades={[makeTrade({})]} />);
    expect(html).toContain("뉴스·공시·수급은 현재 판단에 반영되지 않음");
  });

  it("marks that only the technical axis is computed in Phase A", () => {
    const html = renderToStaticMarkup(<TradesTable trades={[makeTrade({})]} />);
    expect(html).toContain("기술적 축만 계산됨");
  });

  it("renders the uncomputed-axis label for news/disclosure/flow/macro (P0-2)", () => {
    const html = renderToStaticMarkup(<TradesTable trades={[makeTrade({})]} />);
    expect(html).toContain("미수집/판단 불가");
  });
});

describe("TradesTable decision-based display (P0-1)", () => {
  it("renders signal_summary as-is for a FORCED_SELL row (no score recompute)", () => {
    const trade = makeTrade({
      decision_type: "FORCED_SELL",
      trigger_rule: "R18",
      signal_summary: "지지선 붕괴 → 강제 전량매도",
    });
    const html = renderToStaticMarkup(<TradesTable trades={[trade]} />);
    expect(html).toContain("강제 전량매도");
  });

  it("shows a 강제매도 chip for FORCED_SELL", () => {
    const trade = makeTrade({ decision_type: "FORCED_SELL", signal_summary: "강제 전량매도" });
    const html = renderToStaticMarkup(<TradesTable trades={[trade]} />);
    expect(html).toContain("강제매도");
  });

  it("shows a 부분매도 chip for PARTIAL_SELL", () => {
    const trade = makeTrade({ decision_type: "PARTIAL_SELL", signal_summary: "적신호 → 부분 매도" });
    const html = renderToStaticMarkup(<TradesTable trades={[trade]} />);
    expect(html).toContain("부분매도");
  });

  it("shows a 전량매도 chip for FULL_SELL", () => {
    const trade = makeTrade({ decision_type: "FULL_SELL", signal_summary: "적신호 → 전량 매도" });
    const html = renderToStaticMarkup(<TradesTable trades={[trade]} />);
    expect(html).toContain("전량매도");
  });

  it("does not render a decision chip for a plain BUY row", () => {
    const trade = makeTrade({
      side: "BUY",
      decision_type: "BUY",
      signal_summary: "골든크로스 → 매수 신호 (20점/A등급)",
      realized_pnl: 0,
    });
    const html = renderToStaticMarkup(<TradesTable trades={[trade]} />);
    expect(html).not.toContain("chip--forced");
    expect(html).not.toContain("chip--partial");
    expect(html).not.toContain("chip--full");
  });
});

describe("TradesTable realized-pnl accessibility idiom", () => {
  it("pairs the pnl color with a ▲/▼ arrow (aria-hidden), not color alone", () => {
    const lossTrade = makeTrade({ realized_pnl: -100 });
    const html = renderToStaticMarkup(<TradesTable trades={[lossTrade]} />);
    expect(html).toContain('aria-hidden="true">▼');
  });

  it("shows ▲ for a gain and no arrow for a BUY row (—)", () => {
    const gainTrade = makeTrade({ realized_pnl: 250 });
    const html = renderToStaticMarkup(<TradesTable trades={[gainTrade]} />);
    expect(html).toContain('aria-hidden="true">▲');

    const buyTrade = makeTrade({ side: "BUY", decision_type: "BUY", realized_pnl: 0 });
    const buyHtml = renderToStaticMarkup(<TradesTable trades={[buyTrade]} />);
    expect(buyHtml).toContain("—");
  });
});

describe("TradesTable pagination", () => {
  const trades = [makeTrade({})];

  it("shows the page position and total count", () => {
    const html = renderToStaticMarkup(
      <TradesTable trades={trades} pagination={{ page: 2, pageSize: 20, total: 45 }} />
    );
    expect(html).toContain("2 / 3");
    expect(html).toContain("45");
  });

  it("disables the 이전 button on the first page", () => {
    const html = renderToStaticMarkup(
      <TradesTable trades={trades} pagination={{ page: 1, pageSize: 20, total: 45 }} />
    );
    expect(html).toMatch(/aria-label="이전 페이지"[^>]*disabled/);
    expect(html).not.toMatch(/aria-label="다음 페이지"[^>]*disabled/);
  });

  it("disables the 다음 button on the last page", () => {
    const html = renderToStaticMarkup(
      <TradesTable trades={trades} pagination={{ page: 3, pageSize: 20, total: 45 }} />
    );
    expect(html).toContain("3 / 3");
    expect(html).toMatch(/aria-label="다음 페이지"[^>]*disabled/);
    expect(html).not.toMatch(/aria-label="이전 페이지"[^>]*disabled/);
  });
});

describe("TradesTable 포지션 생애 view", () => {
  function makeLifecycle(overrides: Partial<LifecycleOut>): LifecycleOut {
    return {
      symbol: "005930",
      name: "삼성전자",
      market: "KR",
      entry_date: "2026-06-01",
      exit_date: null,
      open: true,
      trades: [makeTrade({ side: "BUY", decision_type: "BUY", realized_pnl: 0 })],
      qty_peak: 10,
      realized_pnl_sum: -50000,
      entry_trigger: "R1",
      ...overrides,
    };
  }

  it("shows 진행중 for an open lifecycle and the bundled realized pnl sum", () => {
    const life = makeLifecycle({ open: true, exit_date: null, realized_pnl_sum: -50000 });
    const html = renderToStaticMarkup(
      <TradesTable trades={[]} view="lifecycle" lifecycles={[life]} />
    );
    expect(html).toContain("진행중");
    expect(html).toContain("-₩50,000");
  });

  it("does not show 진행중 for a closed lifecycle and shows the exit date instead", () => {
    const life = makeLifecycle({
      open: false,
      exit_date: "2026-06-20",
      realized_pnl_sum: 12000,
    });
    const html = renderToStaticMarkup(
      <TradesTable trades={[]} view="lifecycle" lifecycles={[life]} />
    );
    expect(html).not.toContain("진행중");
    expect(html).toContain("2026-06-20");
    expect(html).toContain("+₩12,000");
  });

  it("shows an empty state when there are no lifecycles", () => {
    const html = renderToStaticMarkup(
      <TradesTable trades={[]} view="lifecycle" lifecycles={[]} />
    );
    expect(html).toContain("포지션 생애");
  });
});
