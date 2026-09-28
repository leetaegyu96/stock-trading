import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PositionCard } from "./PositionCard";
import type { AccountSummary, Position } from "../types";

const account: AccountSummary = {
  id: 1,
  kind: "KR",
  currency: "KRW",
  cash: 5_000_000,
  market_value: 1_200_000,
  total_asset: 6_200_000,
  seed: 6_000_000,
  pnl: 200_000,
  return_pct: 3.33,
  position_count: 1,
  equity_spark: [6_000_000, 6_200_000],
  stale: false,
};

function makePosition(overrides: Partial<Position> = {}): Position {
  return {
    id: 1,
    account_id: 1,
    symbol: "005930",
    name: "삼성전자",
    quantity: 100,
    avg_price: 10_000,
    current_price: 10_240,
    market_value: 1_024_000,
    cost_basis: 1_000_000,
    unrealized_pnl: 24_000,
    unrealized_pnl_pct: 2.4,
    opened_at: "2026-09-10T00:00:00Z",
    stale: false,
    sell_rule: {
      id: 1,
      position_id: 1,
      stop_loss_pct: -5,
      take_profit_pct: 15,
      stop_price: 9_500,
      take_price: 11_500,
      quantity: 100,
      active: true,
      created_at: "2026-09-10T00:00:00Z",
      updated_at: "2026-09-10T00:00:00Z",
    },
    ...overrides,
  };
}

describe("PositionCard 손익 표기", () => {
  it("금액과 퍼센트를 함께 보여준다(SPEC §8.2)", () => {
    render(
      <PositionCard
        account={account}
        position={makePosition()}
        onSell={vi.fn()}
        onEditWall={vi.fn()}
      />
    );
    expect(screen.getByTestId("pos-pnl").textContent).toBe("+24,000원 (+2.4%)");
  });

  it("이익은 up(빨강), 손실은 down(파랑) 클래스를 쓴다 — 한국 증권 관례", () => {
    const { rerender } = render(
      <PositionCard
        account={account}
        position={makePosition()}
        onSell={vi.fn()}
        onEditWall={vi.fn()}
      />
    );
    expect(screen.getByTestId("pos-pnl").className).toContain("up");

    rerender(
      <PositionCard
        account={account}
        position={makePosition({
          current_price: 9_700,
          unrealized_pnl: -30_000,
          unrealized_pnl_pct: -3,
        })}
        onSell={vi.fn()}
        onEditWall={vi.fn()}
      />
    );
    expect(screen.getByTestId("pos-pnl").className).toContain("down");
  });
});

describe("PositionCard 매도벽", () => {
  it("규칙이 있으면 게이지에 발동가를 그린다", () => {
    render(
      <PositionCard
        account={account}
        position={makePosition()}
        onSell={vi.fn()}
        onEditWall={vi.fn()}
      />
    );
    expect(screen.getByTestId("wall-now").style.left).toBe("37%");
    expect(screen.getByRole("button", { name: "자동 매도 기준 바꾸기" })).toBeDefined();
  });

  it("규칙이 없으면 정하러 가라고 안내한다", () => {
    render(
      <PositionCard
        account={account}
        position={makePosition({ sell_rule: null })}
        onSell={vi.fn()}
        onEditWall={vi.fn()}
      />
    );
    expect(screen.getByRole("button", { name: "자동으로 팔 기준 정하기" })).toBeDefined();
  });

  it("비활성(이미 발동한) 규칙은 게이지에 그리지 않는다", () => {
    const pos = makePosition();
    const { container } = render(
      <PositionCard
        account={account}
        position={{ ...pos, sell_rule: { ...pos.sell_rule!, active: false } }}
        onSell={vi.fn()}
        onEditWall={vi.fn()}
      />
    );
    expect(container.textContent).toContain("자동으로 팔 기준이 없습니다");
  });
});
