import { describe, expect, it } from "vitest";
import { currencyOf, sellWallGauge, triggerPrice, validateSellRule } from "./sellwall";

describe("triggerPrice — 평단 기준 발동가(SPEC §6.2)", () => {
  it("평단 10,000 · -5% → 9,500", () => {
    expect(triggerPrice(10_000, -5, "KRW")).toBe(9_500);
  });

  it("평단 10,000 · +15% → 11,500", () => {
    expect(triggerPrice(10_000, 15, "KRW")).toBe(11_500);
  });

  it("미설정(null)이면 발동가도 없다", () => {
    expect(triggerPrice(10_000, null, "KRW")).toBeNull();
    expect(triggerPrice(10_000, undefined, "KRW")).toBeNull();
  });

  it("달러는 센트까지 반올림한다", () => {
    expect(triggerPrice(232.45, -5, "USD")).toBe(220.83);
  });
});

describe("sellWallGauge — 현재가 위치 계산(SPEC §9.2)", () => {
  const base = { avgPrice: 10_000, stopPrice: 9_500, takePrice: 11_500 };

  it("SPEC 예시: 현재 10,240 은 9,500~11,500 구간의 37% 지점", () => {
    const g = sellWallGauge({ ...base, currentPrice: 10_240 });
    expect(g.currentPos).toBeCloseTo(37, 5);
    expect(g.lo).toBe(9_500);
    expect(g.hi).toBe(11_500);
  });

  it("평단은 두 벽 사이 25% 지점(예시 기준)", () => {
    const g = sellWallGauge({ ...base, currentPrice: 10_240 });
    expect(g.avgPos).toBeCloseTo(25, 5);
  });

  it("하한선/상한선은 각각 0%·100%", () => {
    const g = sellWallGauge({ ...base, currentPrice: 10_000 });
    expect(g.stopPos).toBe(0);
    expect(g.takePos).toBe(100);
  });

  it("경계값(정확히 같은 가격)도 발동으로 본다", () => {
    expect(sellWallGauge({ ...base, currentPrice: 9_500 }).triggered).toBe("stop");
    expect(sellWallGauge({ ...base, currentPrice: 11_500 }).triggered).toBe("take");
  });

  it("두 조건을 동시에 넘기면 손절(하한)이 우선이다", () => {
    // 뒤집힌 설정으로 양쪽을 동시에 충족시키는 극단 케이스
    const g = sellWallGauge({
      avgPrice: 10_000,
      currentPrice: 10_000,
      stopPrice: 10_500,
      takePrice: 9_500,
    });
    expect(g.triggered).toBe("stop");
  });

  it("구간 안이면 발동 상태가 아니다", () => {
    expect(sellWallGauge({ ...base, currentPrice: 10_240 }).triggered).toBeNull();
  });

  it("현재가가 구간 밖이면 눈금을 넓혀 점이 끝에 숨지 않게 한다", () => {
    const g = sellWallGauge({ ...base, currentPrice: 12_000 });
    expect(g.widened).toBe(true);
    expect(g.hi).toBeGreaterThan(12_000);
    expect(g.currentPos).toBeLessThan(100);
    // 눈금을 넓혀도 발동 판정은 가격 기준 그대로다
    expect(g.triggered).toBe("take");
  });

  it("한쪽만 설정하면 평단을 중심으로 반대편을 대칭으로 잡는다", () => {
    const g = sellWallGauge({
      avgPrice: 10_000,
      currentPrice: 10_000,
      stopPrice: 9_500,
      takePrice: null,
    });
    expect(g.lo).toBe(9_500);
    expect(g.hi).toBe(10_500);
    expect(g.avgPos).toBeCloseTo(50, 5);
    expect(g.takePos).toBeNull();
  });

  it("벽이 하나도 없으면 평단 ±10% 참고 눈금을 쓴다", () => {
    const g = sellWallGauge({
      avgPrice: 10_000,
      currentPrice: 10_000,
      stopPrice: null,
      takePrice: null,
    });
    expect(g.lo).toBe(9_000);
    expect(g.hi).toBe(11_000);
    expect(g.triggered).toBeNull();
  });

  it("위치는 항상 0~100 안에 머문다", () => {
    const g = sellWallGauge({ ...base, currentPrice: 1 });
    expect(g.currentPos).toBeGreaterThanOrEqual(0);
    expect(g.currentPos).toBeLessThanOrEqual(100);
  });
});

describe("validateSellRule (SPEC §6.2 유효성)", () => {
  it("둘 다 비면 거부한다", () => {
    expect(validateSellRule(null, null)).toBe("둘 중 하나는 정해야 자동으로 팔 수 있습니다.");
  });

  it("하한선은 음수여야 한다", () => {
    expect(validateSellRule(5, null)).not.toBeNull();
    expect(validateSellRule(-5, null)).toBeNull();
  });

  it("상한선은 양수이고 900% 이하여야 한다", () => {
    expect(validateSellRule(null, -1)).not.toBeNull();
    expect(validateSellRule(null, 901)).not.toBeNull();
    expect(validateSellRule(null, 900)).toBeNull();
  });

  it("-100% 이하는 거부한다", () => {
    expect(validateSellRule(-100, null)).not.toBeNull();
  });
});

describe("currencyOf", () => {
  it("국내는 원화, 해외는 달러", () => {
    expect(currencyOf("KR")).toBe("KRW");
    expect(currencyOf("US")).toBe("USD");
  });
});
