import { describe, expect, it } from "vitest";
import {
  changeArrow,
  compactMoney,
  compactNumber,
  formatMoney,
  formatSignedMoney,
  kindLabel,
  moneyWithPct,
  reasonInfo,
  shortDate,
  sideLabel,
  signClass,
  signedPct,
  volumeText,
} from "./format";

describe("formatMoney", () => {
  it("원화는 천 단위 구분 + '원' 접미사로 쓴다", () => {
    expect(formatMoney(1_234_567, "KRW")).toBe("1,234,567원");
  });

  it("원화는 소수점을 남기지 않는다", () => {
    expect(formatMoney(1234.6, "KRW")).toBe("1,235원");
  });

  it("달러는 소수 둘째 자리까지 쓴다", () => {
    expect(formatMoney(310.6, "USD")).toBe("$310.60");
  });
});

describe("formatSignedMoney", () => {
  it("이익은 + 를 붙인다", () => {
    expect(formatSignedMoney(17_726, "KRW")).toBe("+17,726원");
  });

  it("손실은 금액 앞에 - 를 붙인다", () => {
    expect(formatSignedMoney(-1_419, "KRW")).toBe("-1,419원");
  });

  it("0 은 부호 없이 쓴다", () => {
    expect(formatSignedMoney(0, "KRW")).toBe("0원");
  });

  it("달러 손실도 기호 앞에 부호가 온다", () => {
    expect(formatSignedMoney(-416.5, "USD")).toBe("-$416.50");
  });
});

describe("signedPct", () => {
  it("양수에는 + 를 붙인다", () => {
    expect(signedPct(1.2345)).toBe("+1.23%");
  });

  it("음수는 - 를 유지한다", () => {
    expect(signedPct(-0.5)).toBe("-0.50%");
  });

  it("정확히 0 에는 부호를 붙이지 않는다", () => {
    expect(signedPct(0)).toBe("0.00%");
  });
});

describe("moneyWithPct — 숫자 옆에 항상 의미(SPEC §8.2)", () => {
  it("금액과 퍼센트를 함께 보여준다", () => {
    expect(moneyWithPct(-320_000, -3.2, "KRW")).toBe("-320,000원 (-3.2%)");
  });
});

describe("signClass — 한국 증권 관례", () => {
  it("상승은 up(빨강)", () => {
    expect(signClass(1)).toBe("up");
  });

  it("하락은 down(파랑)", () => {
    expect(signClass(-1)).toBe("down");
  });

  it("보합은 neutral", () => {
    expect(signClass(0)).toBe("neutral");
  });
});

describe("changeArrow", () => {
  it("색 말고 기호로도 등락을 알린다", () => {
    expect(changeArrow(1.2)).toBe("▲");
    expect(changeArrow(-0.5)).toBe("▼");
    expect(changeArrow(0)).toBe("–");
  });
});

describe("volumeText", () => {
  it("거래량 배수를 평문으로 바꾼다", () => {
    expect(volumeText(2.13)).toBe("평소의 2.1배");
  });

  it("값이 없으면 숫자를 지어내지 않는다", () => {
    expect(volumeText(0)).toBe("거래량 정보 없음");
    expect(volumeText(Number.NaN)).toBe("거래량 정보 없음");
  });
});

describe("compactNumber / compactMoney", () => {
  it("억·만 단위로 줄인다", () => {
    expect(compactNumber(124_328_302)).toBe("1.24억");
    expect(compactNumber(8_240_000)).toBe("824만");
    expect(compactMoney(124_328_302, "KRW")).toBe("1.24억원");
  });

  it("달러는 K/M 로 줄인다", () => {
    expect(compactMoney(70_310.55, "USD")).toBe("$70.3K");
  });
});

describe("reasonInfo — 전문용어 금지(SPEC §8.2)", () => {
  it("'손절'·'익절' 대신 쉬운 말을 쓴다", () => {
    expect(reasonInfo("AUTO_STOP_LOSS").label).toBe("자동 매도 · 떨어져서 팔기");
    expect(reasonInfo("AUTO_TAKE_PROFIT").label).toBe("자동 매도 · 올라서 팔기");
    expect(reasonInfo("AUTO_STOP_LOSS").label).not.toContain("손절");
    expect(reasonInfo("AUTO_TAKE_PROFIT").label).not.toContain("익절");
  });

  it("MANUAL 은 '직접 주문'", () => {
    expect(reasonInfo("MANUAL")).toEqual({ label: "직접 주문", kind: "manual" });
  });

  it("모르는 값은 원문 그대로 둔다", () => {
    expect(reasonInfo("SOMETHING")).toEqual({ label: "SOMETHING", kind: "unknown" });
  });
});

describe("sideLabel / kindLabel / shortDate", () => {
  it("side 를 한글로", () => {
    expect(sideLabel("BUY")).toBe("매수");
    expect(sideLabel("SELL")).toBe("매도");
  });

  it("캐릭터 종류를 한글로", () => {
    expect(kindLabel("KR")).toBe("국내 주식");
    expect(kindLabel("US")).toBe("해외 주식");
  });

  it("ISO 를 날짜로 줄인다", () => {
    expect(shortDate("2026-07-08T05:00:00Z")).toBe("2026-07-08");
    expect(shortDate("nope")).toBe("nope");
  });
});
