import { describe, expect, it } from "vitest";
import { formatAmount, formatDecimalRupees, formatPaise, paiseToAmount } from "./money.ts";

describe("money", () => {
  it("formats paise as rupees with Indian grouping", () => {
    expect(formatPaise(149900)).toBe("Rs 1,499.00");
    expect(formatPaise(149950n)).toBe("Rs 1,499.50");
    expect(formatPaise(12345678900)).toBe("Rs 12,34,56,789.00");
    expect(formatPaise(0)).toBe("Rs 0.00");
    expect(formatPaise(-100)).toBe("-Rs 1.00");
    expect(formatPaise(5)).toBe("Rs 0.05");
  });

  it("formats decimal strings and converts paise back to them", () => {
    expect(formatAmount("1499.00")).toBe("Rs 1,499.00");
    expect(formatAmount("99")).toBe("Rs 99.00");
    expect(paiseToAmount(149950)).toBe("1499.50");
  });
});

describe("formatDecimalRupees", () => {
  it("keeps every place the ledger holds and groups the whole part the en-IN way", () => {
    expect(formatDecimalRupees("0.0012")).toBe("Rs 0.0012");
    expect(formatDecimalRupees("20000")).toBe("Rs 20,000.00");
    expect(formatDecimalRupees("1234567.5")).toBe("Rs 12,34,567.50");
    expect(formatDecimalRupees("12.000000")).toBe("Rs 12.00");
    expect(formatDecimalRupees("-3.25")).toBe("-Rs 3.25");
    expect(formatDecimalRupees("123456789012345678901.01")).toBe(
      "Rs 12,34,56,78,90,12,34,56,78,901.01",
    );
  });

  it("refuses text that is not a decimal", () => {
    expect(() => formatDecimalRupees("1,000")).toThrow(/not a money amount/);
    expect(() => formatDecimalRupees("1e3")).toThrow(/not a money amount/);
  });
});
