import { describe, expect, it } from "vitest";
import {
  addDaysToKey,
  daysBetween,
  dueRelative,
  formatDate,
  formatDateTime,
  formatDueDate,
  isDateKey,
  istDateKey,
  todayKey,
} from "./dates.ts";

const words = {
  today: "today",
  tomorrow: "tomorrow",
  inDays: (n: number) => `in ${n} days`,
  overdue: (n: number) => `overdue by ${n} days`,
};

describe("date keys", () => {
  it("validates calendar dates", () => {
    expect(isDateKey("2026-04-10")).toBe(true);
    expect(isDateKey("2026-02-30")).toBe(false);
    expect(isDateKey("2026-4-1")).toBe(false);
    expect(isDateKey("10/04/2026")).toBe(false);
  });

  it("takes the IST calendar date of an instant, not the UTC one", () => {
    expect(istDateKey(new Date("2026-04-10T20:00:00Z"))).toBe("2026-04-11");
    expect(istDateKey(new Date("2026-04-10T18:29:00Z"))).toBe("2026-04-10");
    expect(todayKey(new Date("2026-12-31T19:00:00Z"))).toBe("2027-01-01");
  });

  it("does whole-day arithmetic", () => {
    expect(daysBetween("2026-03-30", "2026-04-02")).toBe(3);
    expect(daysBetween("2026-04-02", "2026-03-30")).toBe(-3);
    expect(addDaysToKey("2026-03-30", 3)).toBe("2026-04-02");
    expect(addDaysToKey("2027-01-01", -1)).toBe("2026-12-31");
    expect(() => daysBetween("nope", "2026-04-02")).toThrow(/not a date/);
  });
});

describe("formatting", () => {
  it("renders dates in en-IN style and instants in IST", () => {
    expect(formatDate("2026-04-10")).toBe("10 Apr 2026");
    expect(formatDate(new Date("2026-04-10T20:00:00Z"))).toBe("11 Apr 2026");
    expect(formatDate("2026-04-10T20:00:00Z")).toBe("11 Apr 2026");
    const text = formatDateTime("2026-04-10T12:00:00Z");
    expect(text).toMatch(/^10 Apr 2026, 5:30 pm IST$/i);
  });

  it("describes a due date relative to today in IST", () => {
    const now = new Date("2026-04-10T05:00:00Z");
    expect(dueRelative("2026-04-10", now)).toEqual({ kind: "today" });
    expect(dueRelative("2026-04-11", now)).toEqual({ kind: "tomorrow" });
    expect(dueRelative("2026-04-20", now)).toEqual({ kind: "in_days", days: 10 });
    expect(dueRelative("2026-04-08", now)).toEqual({ kind: "overdue", days: 2 });
    expect(formatDueDate("2026-04-20", words, now)).toBe("20 Apr 2026 (in 10 days)");
    expect(formatDueDate("2026-04-10", words, now)).toBe("10 Apr 2026 (today)");
    expect(formatDueDate("2026-04-11", words, now)).toBe("11 Apr 2026 (tomorrow)");
    expect(formatDueDate("2026-04-08", words, now)).toBe("8 Apr 2026 (overdue by 2 days)");
  });
});
