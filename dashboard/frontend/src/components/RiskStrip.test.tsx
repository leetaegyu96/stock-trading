import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { RiskStrip } from "./RiskStrip";
import type { CharacterRiskOut } from "../types";

function makeRisk(overrides: Partial<CharacterRiskOut>): CharacterRiskOut {
  return {
    character: "국내형",
    cash_ratio: 0.35,
    total_exposure_pct: 0.65,
    max_position_weight_pct: 0.18,
    daily_pnl_krw: 125_000,
    ...overrides,
  };
}

describe("RiskStrip", () => {
  it("shows an empty state when there is no risk data", () => {
    const html = renderToStaticMarkup(<RiskStrip risk={[]} />);
    expect(html).toContain("위험 데이터가 없습니다.");
  });

  it("renders all four risk columns, including 종목 집중 (not 업종)", () => {
    const html = renderToStaticMarkup(<RiskStrip risk={[makeRisk({})]} />);
    expect(html).toContain("현금비중");
    expect(html).toContain("총노출");
    expect(html).toContain("최대 보유 비중(종목 집중)");
    expect(html).not.toContain("업종 집중");
    expect(html).toContain("일 손익");
  });

  it("never renders a 업종 or 실적일 column", () => {
    const html = renderToStaticMarkup(<RiskStrip risk={[makeRisk({})]} />);
    expect(html).not.toContain("업종");
    expect(html).not.toContain("실적일");
  });

  it("shows the ▲ arrow alongside a positive daily pnl", () => {
    const html = renderToStaticMarkup(<RiskStrip risk={[makeRisk({ daily_pnl_krw: 50_000 })]} />);
    expect(html).toContain("▲");
  });

  it("shows the ▼ arrow alongside a negative daily pnl", () => {
    const html = renderToStaticMarkup(<RiskStrip risk={[makeRisk({ daily_pnl_krw: -50_000 })]} />);
    expect(html).toContain("▼");
  });

  it("renders one row per character", () => {
    const html = renderToStaticMarkup(
      <RiskStrip risk={[makeRisk({ character: "국내형" }), makeRisk({ character: "해외형" })]} />
    );
    expect(html).toContain("국내형");
    expect(html).toContain("해외형");
  });
});
