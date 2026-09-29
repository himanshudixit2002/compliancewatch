import { describe, expect, it } from "vitest";
import { DEFAULT_QUIET_HOURS, describeQuietHours, isClockTime } from "./quiet-hours";

describe("quiet hours", () => {
  it("accepts HH:MM on the 24-hour clock only", () => {
    expect(isClockTime("00:00")).toBe(true);
    expect(isClockTime("23:59")).toBe(true);
    expect(isClockTime("24:00")).toBe(false);
    expect(isClockTime("7:00")).toBe(false);
    expect(isClockTime("07:60")).toBe(false);
  });

  it("describes a window in the day, across midnight, and none", () => {
    expect(describeQuietHours("13:00", "14:30")).toBe("13:00 to 14:30 IST");
    expect(describeQuietHours(DEFAULT_QUIET_HOURS.start, DEFAULT_QUIET_HOURS.end)).toBe(
      "21:00 to 08:00 IST, across midnight",
    );
    expect(describeQuietHours("22:00", "22:00")).toBe("No quiet hours");
  });
});
