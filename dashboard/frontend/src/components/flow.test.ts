import { describe, expect, it } from "vitest";
import { isPositiveAmount, parseAmountInput } from "./flow";

describe("parseAmountInput", () => {
  it("parses a plain integer string", () => {
    expect(parseAmountInput("1000000")).toBe(1000000);
  });

  it("strips thousand-separator commas and spaces", () => {
    expect(parseAmountInput("1,000,000")).toBe(1000000);
    expect(parseAmountInput(" 500 000 ")).toBe(500000);
  });

  it("parses decimal amounts", () => {
    expect(parseAmountInput("12.5")).toBe(12.5);
  });

  it("returns null for empty input", () => {
    expect(parseAmountInput("")).toBeNull();
    expect(parseAmountInput("   ")).toBeNull();
  });

  it("returns null for non-numeric input", () => {
    expect(parseAmountInput("abc")).toBeNull();
    expect(parseAmountInput("1e10")).toBeNull();
    expect(parseAmountInput("-1000")).toBeNull();
  });
});

describe("isPositiveAmount", () => {
  it("accepts positive numbers", () => {
    expect(isPositiveAmount(1)).toBe(true);
  });

  it("rejects zero", () => {
    expect(isPositiveAmount(0)).toBe(false);
  });

  it("rejects null", () => {
    expect(isPositiveAmount(null)).toBe(false);
  });
});
