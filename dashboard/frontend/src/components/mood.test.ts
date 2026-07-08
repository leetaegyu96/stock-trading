import { describe, expect, it } from "vitest";
import { moodFromPnl } from "./mood";

describe("moodFromPnl", () => {
  it("maps a strong gain (+2%) to happy", () => {
    expect(moodFromPnl(2)).toBe("happy");
  });

  it("maps a mild gain (+0.5%) to smile", () => {
    expect(moodFromPnl(0.5)).toBe("smile");
  });

  it("maps exactly 0% to neutral", () => {
    expect(moodFromPnl(0)).toBe("neutral");
  });

  it("maps a loss (-1%) to down", () => {
    expect(moodFromPnl(-1)).toBe("down");
  });

  it("treats the >1.5 boundary as exclusive (1.5 itself is smile, not happy)", () => {
    expect(moodFromPnl(1.5)).toBe("smile");
  });

  it("treats just above the boundary (1.50001) as happy", () => {
    expect(moodFromPnl(1.50001)).toBe("happy");
  });
});
