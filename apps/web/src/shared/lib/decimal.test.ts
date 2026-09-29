import { describe, expect, it } from "vitest";
import {
  addAmounts,
  compareAmounts,
  fromPaise,
  isAmount,
  subtractAmounts,
  toPaise,
} from "./decimal.ts";

describe("decimal amounts", () => {
  it("converts between decimal strings and paise without floats", () => {
    expect(toPaise("1499.50")).toBe(149950n);
    expect(toPaise("1499.5")).toBe(149950n);
    expect(toPaise("1499")).toBe(149900n);
    expect(toPaise("-0.01")).toBe(-1n);
    expect(fromPaise(149950n)).toBe("1499.50");
    expect(fromPaise(5)).toBe("0.05");
    expect(fromPaise(-1n)).toBe("-0.01");
    expect(fromPaise(12345678901234567890n)).toBe("123456789012345678.90");
  });

  it("rejects malformed amounts and more than two decimals", () => {
    expect(() => toPaise("1.234")).toThrow(/not a money amount/);
    expect(() => toPaise("1,499.00")).toThrow(/not a money amount/);
    expect(() => toPaise("abc")).toThrow(/not a money amount/);
    expect(isAmount("10.10")).toBe(true);
    expect(isAmount("10.")).toBe(false);
  });

  it("adds, subtracts and compares exactly", () => {
    expect(addAmounts("0.10", "0.20")).toBe("0.30");
    expect(subtractAmounts("1.00", "1.10")).toBe("-0.10");
    expect(compareAmounts("1.10", "1.1")).toBe(0);
    expect(compareAmounts("1.09", "1.10")).toBe(-1);
    expect(compareAmounts("2", "1.99")).toBe(1);
  });
});
