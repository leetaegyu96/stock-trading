import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SellWallGauge } from "./SellWallGauge";

describe("SellWallGauge", () => {
  it("현재가 점을 계산된 위치(37%)에 놓는다", () => {
    render(
      <SellWallGauge
        avgPrice={10_000}
        currentPrice={10_240}
        stopPrice={9_500}
        takePrice={11_500}
        currency="KRW"
      />
    );
    const dot = screen.getByTestId("wall-now");
    expect(dot.style.left).toBe("37%");
  });

  it("두 발동가를 금액으로 함께 보여준다", () => {
    render(
      <SellWallGauge
        avgPrice={10_000}
        currentPrice={10_240}
        stopPrice={9_500}
        takePrice={11_500}
        currency="KRW"
      />
    );
    expect(screen.getByText("9,500원")).toBeDefined();
    expect(screen.getByText("11,500원")).toBeDefined();
  });

  it("전문용어 대신 쉬운 말을 쓴다(SPEC §8.2)", () => {
    const { container } = render(
      <SellWallGauge
        avgPrice={10_000}
        currentPrice={10_240}
        stopPrice={9_500}
        takePrice={11_500}
        currency="KRW"
      />
    );
    expect(container.textContent).toContain("이만큼 떨어지면 팔기");
    expect(container.textContent).toContain("이만큼 오르면 팔기");
    expect(container.textContent).not.toContain("손절");
    expect(container.textContent).not.toContain("익절");
  });

  it("현재가와 평단을 퍼센트와 함께 적는다", () => {
    const { container } = render(
      <SellWallGauge
        avgPrice={10_000}
        currentPrice={10_240}
        stopPrice={9_500}
        takePrice={11_500}
        currency="KRW"
      />
    );
    expect(container.textContent).toContain("(+2.4%)");
  });

  it("발동선에 닿으면 곧 팔린다고 알린다", () => {
    const { container } = render(
      <SellWallGauge
        avgPrice={10_000}
        currentPrice={11_600}
        stopPrice={9_500}
        takePrice={11_500}
        currency="KRW"
      />
    );
    expect(container.textContent).toContain("자동으로 팔립니다");
  });

  it("벽이 없으면 다음 행동을 알려주는 문구를 낸다", () => {
    const { container } = render(
      <SellWallGauge
        avgPrice={10_000}
        currentPrice={10_000}
        stopPrice={null}
        takePrice={null}
        currency="KRW"
      />
    );
    expect(container.textContent).toContain("자동으로 팔 기준이 없습니다");
  });
});
