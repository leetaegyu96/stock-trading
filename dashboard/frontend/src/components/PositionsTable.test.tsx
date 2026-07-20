import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { PositionsTable } from "./PositionsTable";
import type { PositionOut } from "../types";

function makePosition(overrides: Partial<PositionOut>): PositionOut {
  return {
    symbol: "005930",
    name: "삼성전자",
    market: "KR",
    quantity: 10,
    avg_price: 70000,
    opened_date: "2026-07-01",
    current_price: 75000,
    eval_value: 750000,
    pnl_pct: 0.07,
    stale: false,
    weight_pct: 0.18,
    entry_trigger: "G1 돌파",
    current_red_score: 1,
    stop_px: 68000,
    trail_px: 71000,
    stop_distance_pct: 0.093,
    potential_loss: 20000,
    pending_sell: false,
    as_of: "2026-07-20",
    ...overrides,
  };
}

describe("PositionsTable (decision-board extension)", () => {
  it("shows an empty state when there are no positions", () => {
    const html = renderToStaticMarkup(<PositionsTable positions={[]} />);
    expect(html).toContain("보유 종목이 없습니다.");
  });

  it("renders the extended risk columns", () => {
    const html = renderToStaticMarkup(<PositionsTable positions={[makePosition({})]} />);
    expect(html).toContain("비중");
    expect(html).toContain("진입사유");
    expect(html).toContain("현재 적신호");
    expect(html).toContain("손절가");
    expect(html).toContain("트레일가");
    expect(html).toContain("거리%");
    expect(html).toContain("잠재손실");
    expect(html).toContain("매도대기");
    expect(html).toContain("기준시각");
    expect(html).toContain("G1 돌파");
  });

  it("never renders a 업종 or 실적일 column", () => {
    const html = renderToStaticMarkup(<PositionsTable positions={[makePosition({})]} />);
    expect(html).not.toContain("업종");
    expect(html).not.toContain("실적일");
  });

  it("renders a dash for all-null decision-board fields instead of crashing", () => {
    const html = renderToStaticMarkup(
      <PositionsTable
        positions={[
          makePosition({
            weight_pct: null,
            entry_trigger: "",
            current_red_score: null,
            stop_px: null,
            trail_px: null,
            stop_distance_pct: null,
            potential_loss: null,
            pending_sell: false,
            as_of: null,
          }),
        ]}
      />
    );
    expect(html).toContain("삼성전자");
    expect((html.match(/—/g) ?? []).length).toBeGreaterThan(0);
  });

  it("marks a pending-sell position distinctly", () => {
    const html = renderToStaticMarkup(
      <PositionsTable positions={[makePosition({ pending_sell: true })]} />
    );
    expect(html).toContain("대기중");
  });

  it("formats potential_loss as KRW (원화 환산) regardless of market", () => {
    const html = renderToStaticMarkup(
      <PositionsTable positions={[makePosition({ market: "US", potential_loss: 30000 })]} />
    );
    expect(html).toContain("₩30,000");
  });
});
