import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { EquityChart } from "./EquityChart";
import type { EquityPoint } from "../types";

function makePoints(): EquityPoint[] {
  return [
    { ts: "2026-06-01T00:00:00Z", equity_krw: 1_000_000 },
    { ts: "2026-06-15T00:00:00Z", equity_krw: 1_050_000 },
    { ts: "2026-07-01T00:00:00Z", equity_krw: 1_100_000 },
  ];
}

describe("EquityChart 구간 수익률 라벨/TWR 툴팁", () => {
  it("labels the period change as 선택 기간 수익률", () => {
    const html = renderToStaticMarkup(<EquityChart points={makePoints()} />);
    expect(html).toContain("선택 기간 수익률");
  });

  it("exposes a TWR explanation via a title attribute (SSR-verifiable)", () => {
    const html = renderToStaticMarkup(<EquityChart points={makePoints()} />);
    expect(html).toMatch(/title="[^"]*TWR[^"]*"/);
  });

  it("still shows the empty state without the period label when there are no points", () => {
    const html = renderToStaticMarkup(<EquityChart points={[]} />);
    expect(html).toContain("자산곡선 데이터가 없습니다.");
    expect(html).not.toContain("선택 기간 수익률");
  });
});
