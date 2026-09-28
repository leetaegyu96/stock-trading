import { describe, expect, it } from "vitest";
import {
  buyBlockReason,
  estimateBuy,
  estimateRealizedPnl,
  estimateSell,
  maxAffordableQuantity,
  roundMinor,
  sellBlockReason,
} from "./money";

describe("roundMinor — 백엔드와 같은 round-half-up", () => {
  it("원 단위에서 0.5 는 올린다", () => {
    expect(roundMinor(1234.5, "KRW")).toBe(1235);
    expect(roundMinor(1234.4, "KRW")).toBe(1234);
  });

  it("달러는 센트까지 남긴다", () => {
    expect(roundMinor(10.005, "USD")).toBe(10.01);
    expect(roundMinor(10.004, "USD")).toBe(10.0);
  });
});

describe("estimateBuy — 매수 예상금액(수수료 포함, SPEC §2.3)", () => {
  it("국내는 0.015% 수수료를 더한다", () => {
    // 78,600 × 10 = 786,000 → 수수료 786,000 × 0.00015 = 117.9 → 118
    const est = estimateBuy(78_600, 10, "KR", "KRW");
    expect(est.gross).toBe(786_000);
    expect(est.fee).toBe(118);
    expect(est.total).toBe(786_118);
  });

  it("해외는 0.09% 수수료를 더한다", () => {
    // 232.45 × 4 = 929.80 → 수수료 929.80 × 0.0009 = 0.83682 → 0.84
    const est = estimateBuy(232.45, 4, "US", "USD");
    expect(est.gross).toBe(929.8);
    expect(est.fee).toBe(0.84);
    expect(est.total).toBe(930.64);
  });

  it("수량 0 이면 모두 0", () => {
    expect(estimateBuy(78_600, 0, "KR", "KRW")).toEqual({ gross: 0, fee: 0, total: 0 });
  });
});

describe("estimateSell — 매도는 수수료 + (국내만) 거래세", () => {
  it("국내는 0.015% 수수료와 0.15% 세금을 뺀다", () => {
    // 100,000 × 10 = 1,000,000 → fee 150, tax 1,500
    const est = estimateSell(100_000, 10, "KR", "KRW");
    expect(est.gross).toBe(1_000_000);
    expect(est.fee).toBe(150);
    expect(est.tax).toBe(1_500);
    expect(est.net).toBe(998_350);
  });

  it("해외는 세금이 없다", () => {
    const est = estimateSell(200, 10, "US", "USD");
    expect(est.gross).toBe(2000);
    expect(est.tax).toBe(0);
    expect(est.fee).toBe(1.8);
    expect(est.net).toBe(1998.2);
  });
});

describe("estimateRealizedPnl", () => {
  it("비용을 뺀 뒤의 손익을 낸다", () => {
    // (110,000 − 100,000) × 10 = 100,000, fee 165, tax 1,650
    expect(estimateRealizedPnl(110_000, 100_000, 10, "KR", "KRW")).toBe(100_000 - 165 - 1_650);
  });

  it("손실이면 음수가 나온다", () => {
    expect(estimateRealizedPnl(90_000, 100_000, 10, "KR", "KRW")).toBeLessThan(0);
  });
});

describe("maxAffordableQuantity — 수수료까지 감안한 최대 수량", () => {
  it("수수료를 포함해도 잔고를 넘지 않는다", () => {
    const cash = 1_000_000;
    const qty = maxAffordableQuantity(cash, 78_600, "KR", "KRW");
    expect(estimateBuy(78_600, qty, "KR", "KRW").total).toBeLessThanOrEqual(cash);
    expect(estimateBuy(78_600, qty + 1, "KR", "KRW").total).toBeGreaterThan(cash);
  });

  it("현금이나 가격이 0 이면 0 주", () => {
    expect(maxAffordableQuantity(0, 100, "KR", "KRW")).toBe(0);
    expect(maxAffordableQuantity(1000, 0, "KR", "KRW")).toBe(0);
  });
});

describe("buyBlockReason — 잔고 초과 시 안내(SPEC §9.2)", () => {
  it("잔고 안이면 막지 않는다", () => {
    expect(buyBlockReason(10, 1_000_000, 78_600, "KR", "KRW")).toBeNull();
  });

  it("수수료 때문에 1원이라도 넘으면 막는다", () => {
    // 786,118 이 필요한데 786,117 만 있는 경계
    expect(buyBlockReason(10, 786_117, 78_600, "KR", "KRW")).toBe(
      "가진 현금보다 많습니다. 수량을 줄여보세요."
    );
    expect(buyBlockReason(10, 786_118, 78_600, "KR", "KRW")).toBeNull();
  });

  it("수량이 0 이하거나 정수가 아니면 막는다", () => {
    expect(buyBlockReason(0, 1_000_000, 78_600, "KR", "KRW")).toBe("살 수량을 1주 이상 입력하세요.");
    expect(buyBlockReason(1.5, 1_000_000, 78_600, "KR", "KRW")).toBe("살 수량을 1주 이상 입력하세요.");
  });

  it("현재가를 못 받았으면 막는다", () => {
    expect(buyBlockReason(1, 1_000_000, 0, "KR", "KRW")).toBe(
      "현재가를 불러오지 못해 지금은 살 수 없습니다."
    );
  });
});

describe("sellBlockReason", () => {
  it("가진 수량 안이면 막지 않는다", () => {
    expect(sellBlockReason(5, 10, 1000)).toBeNull();
  });

  it("가진 수량을 넘으면 막고 수량을 알려준다", () => {
    expect(sellBlockReason(11, 10, 1000)).toBe("가진 수량(10주)보다 많습니다.");
  });

  it("0 주는 막는다", () => {
    expect(sellBlockReason(0, 10, 1000)).toBe("팔 수량을 1주 이상 입력하세요.");
  });
});
