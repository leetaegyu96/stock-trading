import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { SellWallEditor } from "./SellWallEditor";
import type { AccountSummary, Position } from "../types";

const account: AccountSummary = {
  id: 1,
  kind: "KR",
  currency: "KRW",
  cash: 1_000_000,
  market_value: 1_000_000,
  total_asset: 2_000_000,
  seed: 2_000_000,
  pnl: 0,
  return_pct: 0,
  position_count: 1,
  equity_spark: [2_000_000],
  stale: false,
};

const position: Position = {
  id: 7,
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
  sell_rule: null,
};

function open(overrides: Partial<Position> = {}) {
  const onSave = vi.fn().mockResolvedValue(undefined);
  const onRemove = vi.fn().mockResolvedValue(undefined);
  const onClose = vi.fn();
  render(
    <SellWallEditor
      account={account}
      position={{ ...position, ...overrides }}
      onSave={onSave}
      onRemove={onRemove}
      onClose={onClose}
    />
  );
  return { onSave, onRemove, onClose };
}

describe("SellWallEditor — 퍼센트를 즉시 금액으로 환산(SPEC §8.1 #6)", () => {
  it("기본값 -5% / +15% 를 발동가 금액으로 보여준다", () => {
    open();
    expect(screen.getByTestId("stop-price").textContent).toContain("9,500원");
    expect(screen.getByTestId("take-price").textContent).toContain("11,500원");
  });

  it("슬라이더를 움직이면 금액이 즉시 따라간다", () => {
    open();
    fireEvent.change(screen.getByLabelText("이만큼 떨어지면 팔기 퍼센트"), {
      target: { value: "-10" },
    });
    expect(screen.getByTestId("stop-price").textContent).toContain("9,000원");
  });

  it("발동했을 때의 손익까지 미리 알려준다", () => {
    open();
    // 9,500 × 100 = 950,000 → 손익 -50,000 − 수수료 142 − 세금 1,425
    expect(screen.getByTestId("stop-price").textContent).toContain("-51,568원");
  });

  it("체크를 끄면 그 기준은 사라진다", () => {
    open();
    fireEvent.click(screen.getByLabelText("이만큼 떨어지면 팔기"));
    expect(screen.queryByTestId("stop-price")).toBeNull();
  });

  it("둘 다 끄면 저장 버튼이 잠기고 이유를 알려준다", () => {
    open();
    fireEvent.click(screen.getByLabelText("이만큼 떨어지면 팔기"));
    fireEvent.click(screen.getByLabelText("이만큼 오르면 팔기"));
    expect(screen.getByRole("button", { name: "저장" })).toHaveProperty("disabled", true);
    expect(screen.getByText("둘 중 하나는 정해야 자동으로 팔 수 있습니다.")).toBeDefined();
  });

  it("저장하면 퍼센트와 수량이 함께 전달된다", () => {
    const { onSave } = open();
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    expect(onSave).toHaveBeenCalledWith({
      stop_loss_pct: -5,
      take_profit_pct: 15,
      quantity: 100,
    });
  });

  it("체결가가 발동선과 다를 수 있다는 점을 미리 고지한다(SPEC §6.2)", () => {
    const { container } = render(
      <SellWallEditor
        account={account}
        position={position}
        onSave={vi.fn()}
        onRemove={vi.fn()}
        onClose={vi.fn()}
      />
    );
    expect(container.textContent).toContain("정한 가격에 딱 맞춰 팔리지 않을 수 있습니다");
  });

  it("이미 규칙이 있으면 해제 버튼을 준다", () => {
    open({
      sell_rule: {
        id: 3,
        position_id: 7,
        stop_loss_pct: -8,
        take_profit_pct: null,
        stop_price: 9_200,
        take_price: null,
        quantity: 100,
        active: true,
        created_at: "2026-09-10T00:00:00Z",
        updated_at: "2026-09-10T00:00:00Z",
      },
    });
    expect(screen.getByRole("button", { name: "기준 없애기" })).toBeDefined();
    expect(screen.getByTestId("stop-price").textContent).toContain("9,200원");
    expect(screen.queryByTestId("take-price")).toBeNull();
  });
});
