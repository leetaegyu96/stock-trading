import { describe, expect, it } from "vitest";
import {
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
