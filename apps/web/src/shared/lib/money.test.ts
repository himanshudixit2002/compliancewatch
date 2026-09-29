import { describe, expect, it } from "vitest";
import { formatAmount, formatPaise, paiseToAmount } from "./money.ts";

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
