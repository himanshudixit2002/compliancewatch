import { describe, expect, it } from "vitest";
import {
  currentFinancialYear,
  financialYearLabel,
  financialYearOf,
  financialYearRange,
  nextFinancialYear,
  parseFinancialYearLabel,
  previousFinancialYear,
} from "./financial-year.ts";

describe("financial years", () => {
  it("start on 1 April", () => {
    expect(financialYearOf("2026-03-31")).toEqual({ start: 2025 });
    expect(financialYearOf("2026-04-01")).toEqual({ start: 2026 });
    expect(financialYearOf("2026-12-15")).toEqual({ start: 2026 });
    expect(() => financialYearOf("2026-13-01")).toThrow(/not a date/);
  });

  it("are labelled start-YY and parse back", () => {
    expect(financialYearLabel({ start: 2026 })).toBe("2026-27");
    expect(financialYearLabel({ start: 2099 })).toBe("2099-00");
    expect(parseFinancialYearLabel("2026-27")).toEqual({ start: 2026 });
    expect(parseFinancialYearLabel("2026-28")).toBeNull();
    expect(parseFinancialYearLabel("2026")).toBeNull();
  });

  it("span April to March and step by one", () => {
    expect(financialYearRange({ start: 2026 })).toEqual({ from: "2026-04-01", to: "2027-03-31" });
    expect(nextFinancialYear({ start: 2026 })).toEqual({ start: 2027 });
    expect(previousFinancialYear({ start: 2026 })).toEqual({ start: 2025 });
  });

  it("uses the IST date for the current year", () => {
    expect(currentFinancialYear(new Date("2026-03-31T20:00:00Z"))).toEqual({ start: 2026 });
    expect(currentFinancialYear(new Date("2026-03-31T10:00:00Z"))).toEqual({ start: 2025 });
  });
});
