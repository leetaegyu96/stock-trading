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

describe("EquityChart 구간 수익률 라벨/툴팁", () => {
  it("labels the period change as 선택 기간 수익률", () => {
    const html = renderToStaticMarkup(<EquityChart points={makePoints()} />);
    expect(html).toContain("선택 기간 수익률");
  });

  it("honestly discloses the chip is a simple return, not TWR-adjusted (SSR-verifiable)", () => {
    const html = renderToStaticMarkup(<EquityChart points={makePoints()} />);
    // 실제 계산은 (last-first)/first 단순 수익률이므로, 툴팁은 그렇게 정직하게 표기해야 한다.
    expect(html).toMatch(/title="[^"]*단순 수익률[^"]*미보정[^"]*"/);
    // TWR을 언급하되, 이 숫자가 TWR "기준"이라고 주장해서는 안 된다 — 지표 패널로의 안내여야 한다.
    expect(html).not.toMatch(/title="TWR\(시간가중수익률\) 기준/);
    expect(html).toMatch(/title="[^"]*TWR[^"]*지표 패널[^"]*"/);
  });

  it("still shows the empty state without the period label when there are no points", () => {
    const html = renderToStaticMarkup(<EquityChart points={[]} />);
    expect(html).toContain("자산곡선 데이터가 없습니다.");
    expect(html).not.toContain("선택 기간 수익률");
  });
});
