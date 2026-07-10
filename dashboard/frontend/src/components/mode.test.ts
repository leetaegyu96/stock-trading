import { describe, expect, it } from "vitest";
import { OPERATING_MODE, OPERATING_MODE_DESC, formatAsOf } from "./mode";

describe("OPERATING_MODE", () => {
  it("is PAPER — this product only ever runs paper/replay, never live orders", () => {
    expect(OPERATING_MODE).toBe("PAPER");
  });

  it("describes KIS as quote-only with no real orders", () => {
    expect(OPERATING_MODE_DESC).toContain("실주문 없음");
  });
});

describe("formatAsOf", () => {
  it("renders a 데이터 기준 timestamp distinct from connection status", () => {
    const ts = new Date("2026-07-10T05:12:34Z");
    expect(formatAsOf(ts)).toBe(`데이터 기준 ${ts.toLocaleTimeString("ko-KR", { hour12: false })}`);
  });

  it("falls back to a no-data label when there is no snapshot yet", () => {
    expect(formatAsOf(null)).toBe("데이터 기준 시각 없음");
  });
});
