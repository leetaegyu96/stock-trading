import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { BuyPanel } from "./BuyPanel";
import type { AccountSummary, Stock } from "../types";

function makeAccount(overrides: Partial<AccountSummary> = {}): AccountSummary {
  return {
    id: 1,
    kind: "KR",
    currency: "KRW",
    cash: 1_000_000,
    market_value: 0,
    total_asset: 1_000_000,
    seed: 1_000_000,
    pnl: 0,
    return_pct: 0,
    position_count: 0,
    equity_spark: [1_000_000],
    stale: false,
    ...overrides,
  };
}

function makeStock(overrides: Partial<Stock> = {}): Stock {
  return {
    symbol: "005930",
    name: "삼성전자",
    price: 78_600,
    change_pct: 1.2,
    spark7: [77_000, 77_500, 78_000, 78_200, 78_100, 78_400, 78_600],
    week_change_pct: 2.1,
    volume: 12_000_000,
    volume_vs_avg: 1.4,
    high_52w: 88_000,
    low_52w: 60_000,
    stale: false,
    ...overrides,
  };
}

const buyButton = () => screen.getByRole("button", { name: /주 사기$/ });

describe("BuyPanel 예상금액", () => {
  it("수량을 바꾸면 수수료 포함 금액이 즉시 다시 계산된다", () => {
    render(<BuyPanel account={makeAccount()} stock={makeStock()} onBuy={vi.fn()} />);
    expect(screen.getByTestId("buy-total").textContent).toBe("78,612원");

    fireEvent.change(screen.getByLabelText("살 수량"), { target: { value: "10" } });
    expect(screen.getByTestId("buy-total").textContent).toBe("786,118원");
  });

  it("+ 버튼으로 수량이 늘어난다", () => {
    render(<BuyPanel account={makeAccount()} stock={makeStock()} onBuy={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("살 수량 1 늘리기"));
    expect((screen.getByLabelText("살 수량") as HTMLInputElement).value).toBe("2");
  });
});

describe("BuyPanel 잔고 초과(SPEC §9.2)", () => {
  it("잔고를 넘는 수량이면 버튼이 잠기고 이유를 알려준다", () => {
    render(
      <BuyPanel account={makeAccount({ cash: 100_000 })} stock={makeStock()} onBuy={vi.fn()} />
    );
    fireEvent.change(screen.getByLabelText("살 수량"), { target: { value: "5" } });

    expect(buyButton()).toHaveProperty("disabled", true);
    expect(screen.getByText("가진 현금보다 많습니다. 수량을 줄여보세요.")).toBeDefined();
  });

  it("살 수 있는 수량이면 버튼이 열린다", () => {
    render(
      <BuyPanel account={makeAccount({ cash: 100_000 })} stock={makeStock()} onBuy={vi.fn()} />
    );
    expect(buyButton()).toHaveProperty("disabled", false);
  });

  it("'가진 현금 전부'는 수수료까지 감안한 수량을 넣는다", () => {
    render(
      <BuyPanel account={makeAccount({ cash: 1_000_000 })} stock={makeStock()} onBuy={vi.fn()} />
    );
    fireEvent.click(screen.getByRole("button", { name: /가진 현금 전부/ }));
    expect((screen.getByLabelText("살 수량") as HTMLInputElement).value).toBe("12");
    expect(buyButton()).toHaveProperty("disabled", false);
  });

  it("수량 0 이면 버튼이 잠긴다", () => {
    render(<BuyPanel account={makeAccount()} stock={makeStock()} onBuy={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("살 수량"), { target: { value: "0" } });
    expect(buyButton()).toHaveProperty("disabled", true);
  });
});

describe("BuyPanel 확인 단계(SPEC §8.2)", () => {
  it("버튼만 눌러서는 주문이 나가지 않고 요약 모달이 먼저 뜬다", () => {
    const onBuy = vi.fn().mockResolvedValue(undefined);
    render(<BuyPanel account={makeAccount()} stock={makeStock()} onBuy={onBuy} />);

    fireEvent.click(buyButton());
    expect(onBuy).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "이대로 살까요?" })).toBeDefined();
  });

  it("모달에서 확정해야 실제로 주문이 나간다", async () => {
    const onBuy = vi.fn().mockResolvedValue(undefined);
    render(<BuyPanel account={makeAccount()} stock={makeStock()} onBuy={onBuy} />);

    fireEvent.change(screen.getByLabelText("살 수량"), { target: { value: "3" } });
    fireEvent.click(buyButton());
    fireEvent.click(screen.getByRole("button", { name: "네, 삽니다" }));

    expect(onBuy).toHaveBeenCalledWith(3);
  });

  it("취소하면 모달이 닫히고 주문은 나가지 않는다", () => {
    const onBuy = vi.fn();
    render(<BuyPanel account={makeAccount()} stock={makeStock()} onBuy={onBuy} />);

    fireEvent.click(buyButton());
    fireEvent.click(screen.getByRole("button", { name: "취소" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onBuy).not.toHaveBeenCalled();
  });
});

describe("BuyPanel 장외 안내(SPEC §5.1-6)", () => {
  it("stale 시세면 마지막 가격 기준임을 밝힌다", () => {
    const { container } = render(
      <BuyPanel account={makeAccount()} stock={makeStock({ stale: true })} onBuy={vi.fn()} />
    );
    expect(container.textContent).toContain("마지막으로 확인된");
  });
});

describe("BuyPanel 은 추천을 하지 않는다(SPEC §4.2)", () => {
  it("점수·추천 문구가 없다", () => {
    const { container } = render(
      <BuyPanel account={makeAccount()} stock={makeStock()} onBuy={vi.fn()} />
    );
    expect(container.textContent).not.toMatch(/추천|점수|신호/);
  });
});
