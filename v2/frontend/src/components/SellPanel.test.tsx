import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { SellPanel } from "./SellPanel";
import type { AccountSummary, Position } from "../types";

function account(kind: "KR" | "US" = "KR"): AccountSummary {
  return {
    id: 1,
    kind,
    currency: kind === "US" ? "USD" : "KRW",
    cash: 0,
    market_value: 1_000_000,
    total_asset: 1_000_000,
    seed: 1_000_000,
    pnl: 0,
    return_pct: 0,
    position_count: 1,
    equity_spark: [1_000_000],
    stale: false,
  };
}

const position: Position = {
  id: 1,
  account_id: 1,
  symbol: "005930",
  name: "삼성전자",
  quantity: 10,
  avg_price: 100_000,
  current_price: 110_000,
  market_value: 1_100_000,
  cost_basis: 1_000_000,
  unrealized_pnl: 100_000,
  unrealized_pnl_pct: 10,
  opened_at: "2026-09-10T00:00:00Z",
  stale: false,
  sell_rule: null,
};

describe("SellPanel", () => {
  it("손에 들어올 돈은 수수료·세금을 뺀 금액이다", () => {
    render(
      <SellPanel open account={account()} position={position} onSell={vi.fn()} onClose={vi.fn()} />
    );
    // 110,000 × 10 = 1,100,000 → 수수료 165, 세금 1,650 → 1,098,185
    expect(screen.getByTestId("sell-net").textContent).toBe("1,098,185원");
  });

  it("해외 캐릭터에는 세금 줄을 보여주지 않는다", () => {
    const { container } = render(
      <SellPanel
        open
        account={account("US")}
        position={position}
        onSell={vi.fn()}
        onClose={vi.fn()}
      />
    );
    expect(container.textContent).not.toContain("세금");
  });

  it("전량 매도면 매도벽도 함께 사라진다고 경고한다", () => {
    const { container } = render(
      <SellPanel open account={account()} position={position} onSell={vi.fn()} onClose={vi.fn()} />
    );
    expect(container.textContent).toContain("자동 매도 기준도 함께 사라집니다");
  });

  it("가진 수량을 넘겨 입력할 수 없다", () => {
    render(
      <SellPanel open account={account()} position={position} onSell={vi.fn()} onClose={vi.fn()} />
    );
    fireEvent.change(screen.getByLabelText("팔 수량"), { target: { value: "99" } });
    expect((screen.getByLabelText("팔 수량") as HTMLInputElement).value).toBe("10");
  });

  it("수량 0 이면 확정 버튼이 잠긴다", () => {
    render(
      <SellPanel open account={account()} position={position} onSell={vi.fn()} onClose={vi.fn()} />
    );
    fireEvent.change(screen.getByLabelText("팔 수량"), { target: { value: "0" } });
    expect(screen.getByRole("button", { name: "팔 수 없음" })).toHaveProperty("disabled", true);
  });

  it("확정하면 고른 수량으로 주문이 나간다", () => {
    const onSell = vi.fn().mockResolvedValue(undefined);
    render(
      <SellPanel open account={account()} position={position} onSell={onSell} onClose={vi.fn()} />
    );
    fireEvent.change(screen.getByLabelText("팔 수량"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "4주 팔기" }));
    expect(onSell).toHaveBeenCalledWith(4);
  });
});
