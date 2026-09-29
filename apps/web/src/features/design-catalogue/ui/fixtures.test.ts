import { describe, expect, it } from "vitest";
import { EXAMPLE_DATE, EXAMPLE_TEXT, FIXTURES } from "./fixtures";

/** Regulatory vocabulary that must never appear in catalogue data or on the catalogue page. */
export const FORBIDDEN_TOKENS =
  /\b(cbic|gst|gstr|gstin|section|sections|rule|rules|notification|notifications|act|acts)\b/i;

describe("catalogue fixtures", () => {
  it("use example text and dates in the year 2000", () => {
    expect(EXAMPLE_TEXT).toBe("Example clause text");
    expect(EXAMPLE_DATE).toMatch(/^2000-/);
    for (const row of FIXTURES.rows) expect(row.due).toMatch(/^2000-/);
    for (const event of FIXTURES.timeline) expect(event.dateTime).toMatch(/^2000-/);
    for (const key of Object.keys(FIXTURES.calendarMarks)) expect(key).toMatch(/^2000-/);
    expect(FIXTURES.calendarMonth.year).toBe(2000);
    expect(FIXTURES.identifier).toMatch(/^0{8}-0{4}-4000-8000-0{12}$/);
  });

  it("contain none of the regulatory tokens", () => {
    const text = JSON.stringify(FIXTURES);
    const hit = FORBIDDEN_TOKENS.exec(text);
    expect(hit?.[0], `found "${hit?.[0]}" in the fixtures`).toBeUndefined();
  });
});
