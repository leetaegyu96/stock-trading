import { describe, expect, it } from "vitest";
import {
  changeArrow,
  formatKrw,
  holdingDays,
  shortDate,
  sideLabel,
  signClass,
  signedPct,
  signalKind,
} from "./format";

describe("formatKrw", () => {
  it("rounds and adds a won sign with thousand separators", () => {
    expect(formatKrw(1234567.8)).toBe("₩1,234,568");
  });
});

describe("signedPct", () => {
  it("prefixes a plus sign for positive values", () => {
    expect(signedPct(1.2345)).toBe("+1.23%");
  });

  it("keeps the minus sign for negative values", () => {
    expect(signedPct(-0.5)).toBe("-0.50%");
  });

  it("does not add a sign for exactly zero", () => {
    expect(signedPct(0)).toBe("0.00%");
  });
});

describe("changeArrow", () => {
  it("shows ▲ for positive change", () => {
    expect(changeArrow(1.2)).toBe("▲");
  });

  it("shows ▼ for negative change", () => {
    expect(changeArrow(-0.5)).toBe("▼");
  });

  it("shows – for exactly zero", () => {
    expect(changeArrow(0)).toBe("–");
  });
});

describe("signClass", () => {
  it("maps positive to up (red convention)", () => {
    expect(signClass(1)).toBe("up");
  });

  it("maps negative to down (blue convention)", () => {
    expect(signClass(-1)).toBe("down");
  });

  it("maps zero to neutral", () => {
    expect(signClass(0)).toBe("neutral");
  });
});

describe("holdingDays", () => {
  it("counts the open day itself as day 1", () => {
    const now = new Date("2026-07-08T00:00:00Z");
    expect(holdingDays("2026-07-08", now)).toBe(1);
  });

  it("counts elapsed days inclusively", () => {
    const now = new Date("2026-07-10T00:00:00Z");
    expect(holdingDays("2026-07-08", now)).toBe(3);
  });

  it("returns 0 for an unparseable date", () => {
    expect(holdingDays("not-a-date")).toBe(0);
  });
});

describe("signalKind", () => {
  it("classifies G-codes as green (buy signal)", () => {
    expect(signalKind("G1")).toBe("green");
  });

  it("classifies R-codes as red (sell signal)", () => {
    expect(signalKind("R3")).toBe("red");
  });

  it("falls back to unknown for other codes", () => {
    expect(signalKind("X9")).toBe("unknown");
  });
});

describe("sideLabel", () => {
  it("translates BUY-ish reasons to 매수", () => {
    expect(sideLabel("BUY")).toBe("매수");
    expect(sideLabel("SIGNAL_BUY")).toBe("매수");
  });

  it("translates SELL-ish reasons to 매도", () => {
    expect(sideLabel("SELL")).toBe("매도");
    expect(sideLabel("SIGNAL_SELL")).toBe("매도");
  });

  it("passes through unknown sides unchanged", () => {
    expect(sideLabel("HOLD")).toBe("HOLD");
  });
});

describe("shortDate", () => {
  it("shortens an ISO timestamp to YYYY-MM-DD", () => {
    expect(shortDate("2026-07-08T05:00:00Z")).toBe("2026-07-08");
  });

  it("returns the original string when unparseable", () => {
    expect(shortDate("nope")).toBe("nope");
  });
});

// ── UI 개편에서 추가된 포맷터 ──
import {
  formatKrwCompact,
  formatPrice,
  formatSignedKrw,
  formatSignedPrice,
  reasonInfo,
  starString,
} from "./format";

describe("formatKrwCompact", () => {
  it("formats 억 with two decimals", () => {
    expect(formatKrwCompact(124_328_302)).toBe("1.24억");
  });
  it("formats 만 rounded", () => {
    expect(formatKrwCompact(82_400_00)).toBe("824만");
  });
  it("keeps small values raw and preserves the sign", () => {
    expect(formatKrwCompact(-1234)).toBe("-1,234");
  });
});

describe("formatSignedKrw", () => {
  it("adds plus for gains", () => {
    expect(formatSignedKrw(17726338)).toBe("+₩17,726,338");
  });
  it("puts the minus before the won sign", () => {
    expect(formatSignedKrw(-1419227)).toBe("-₩1,419,227");
  });
});

describe("formatPrice", () => {
  it("uses won without decimals for KR", () => {
    expect(formatPrice("KR", 265300)).toBe("₩265,300");
  });
  it("uses dollars with two decimals for US", () => {
    expect(formatPrice("US", 310.66)).toBe("$310.66");
  });
});

describe("formatSignedPrice", () => {
  it("signs US pnl in dollars", () => {
    expect(formatSignedPrice("US", -416.5)).toBe("-$416.50");
  });
});

describe("reasonInfo", () => {
  it("maps engine enums to Korean labels", () => {
    expect(reasonInfo("STOP_LOSS")).toEqual({ label: "손절", kind: "stop" });
    expect(reasonInfo("TAKE_PROFIT")).toEqual({ label: "익절", kind: "take" });
    expect(reasonInfo("SIGNAL_BUY").label).toBe("신호 매수");
  });
  it("falls back to the raw value for unknown reasons", () => {
    expect(reasonInfo("SOMETHING")).toEqual({ label: "SOMETHING", kind: "unknown" });
  });

  it("gives trailing stop a beginner-friendly profit-protection label", () => {
    expect(reasonInfo("TRAILING_STOP")).toEqual({
      label: "트레일링 스탑(수익 보호)",
      kind: "take",
    });
  });
});

describe("starString", () => {
  it("renders filled stars up to the given count", () => {
    expect(starString(3)).toBe("★★★☆☆");
  });

  it("renders all filled at max", () => {
    expect(starString(5)).toBe("★★★★★");
  });

  it("clamps out-of-range values", () => {
    expect(starString(0)).toBe("☆☆☆☆☆");
    expect(starString(9)).toBe("★★★★★");
    expect(starString(-2)).toBe("☆☆☆☆☆");
  });
});
