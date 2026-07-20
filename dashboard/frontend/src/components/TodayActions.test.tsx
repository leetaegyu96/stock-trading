import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { TodayActions } from "./TodayActions";
import type { TodayActionsOut } from "../types";

describe("TodayActions", () => {
  it('shows "오늘 예정된 행동 없음" when nothing is pending for any character', () => {
    const actions: TodayActionsOut[] = [
      { character: "국내형", pending_orders: [], forced_sell_alerts: [] },
      { character: "해외형", pending_orders: [], forced_sell_alerts: [] },
    ];
    const html = renderToStaticMarkup(<TodayActions actions={actions} />);
    expect(html).toContain("오늘 예정된 행동 없음");
  });

  it("also shows the empty message for an empty character list", () => {
    const html = renderToStaticMarkup(<TodayActions actions={[]} />);
    expect(html).toContain("오늘 예정된 행동 없음");
  });

  it("renders a pending order with its character and side", () => {
    const actions: TodayActionsOut[] = [
      {
        character: "국내형",
        pending_orders: [
          {
            symbol: "005930",
            name: "삼성전자",
            market: "KR",
            side: "BUY",
            decision_type: "BUY",
            trigger_rule: "G1",
            reason: "SIGNAL_BUY",
          },
        ],
        forced_sell_alerts: [],
      },
    ];
    const html = renderToStaticMarkup(<TodayActions actions={actions} />);
    expect(html).toContain("국내형");
    expect(html).toContain("삼성전자");
    expect(html).toContain("매수");
    expect(html).not.toContain("오늘 예정된 행동 없음");
  });

  it("renders a forced-sell alert distinctly", () => {
    const actions: TodayActionsOut[] = [
      {
        character: "해외형",
        pending_orders: [],
        forced_sell_alerts: [
          {
            symbol: "AAPL",
            name: "애플",
            market: "US",
            date: "2026-07-20",
            realized_pnl: -120.5,
          },
        ],
      },
    ];
    const html = renderToStaticMarkup(<TodayActions actions={actions} />);
    expect(html).toContain("강제매도");
    expect(html).toContain("애플");
  });
});
