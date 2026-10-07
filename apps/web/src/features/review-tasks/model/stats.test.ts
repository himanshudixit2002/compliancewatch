import { describe, expect, it } from "vitest";
import { reviewStatsFromDto } from "@/entities/rule-version/mappers";
import { reviewStatsDto } from "@/test/review-task-fixture";
import { acceptanceText, formatDuration, statsStrip, statsView } from "./stats";

describe("formatDuration", () => {
  it("words a length of time to the minute", () => {
    expect(formatDuration(0)).toBe("Less than a minute");
    expect(formatDuration(59)).toBe("Less than a minute");
    expect(formatDuration(60 * 12)).toBe("12 min");
    expect(formatDuration(3600 * 3 + 60 * 20)).toBe("3 h 20 min");
    expect(formatDuration(86_400 * 2 + 3600 * 4 + 59)).toBe("2 d 4 h");
    expect(formatDuration(-5)).toBe("Less than a minute");
  });
});

describe("the stats", () => {
  it("builds the strip: the counts, the acceptance rate and the oldest wait", () => {
    expect(statsStrip(reviewStatsFromDto(reviewStatsDto()))).toEqual({
      open: 3,
      claimed: 1,
      decided: 4,
      acceptance: "33%",
      oldest: "1 d 2 h",
      statsHref: "/admin/review/stats",
    });
  });

  it("says when no candidate is decided and no task waits", () => {
    const stats = reviewStatsFromDto(
      reviewStatsDto({
        oldest_open_at: null,
        oldest_open_age_seconds: 0,
        median_seconds_to_decide: null,
        candidates: {
          decided: 0,
          approved: 0,
          approved_without_edits: 0,
          rejected: 0,
          acceptance_rate: null,
        },
      }),
    );
    expect(acceptanceText(null)).toBe("None decided yet");
    expect(statsStrip(stats)).toMatchObject({
      acceptance: "None decided yet",
      oldest: "No task waits",
    });
    expect(statsView(stats)).toMatchObject({
      median: "No task decided yet",
      oldest: "No task waits",
      oldestSince: null,
      candidates: { acceptance: "None decided yet", explained: null },
    });
  });

  it("builds the page: the totals, each regulator's row and the rate explained", () => {
    const view = statsView(reviewStatsFromDto(reviewStatsDto()));
    expect(view.byStatus).toEqual({ open: 3, claimed: 1, decided: 4, total: 8 });
    expect(view.regulators).toEqual([
      { regulator: "example_regulator", open: 2, claimed: 1, decided: 4, total: 7 },
      { regulator: "example_other", open: 1, claimed: 0, decided: 0, total: 1 },
    ]);
    expect(view.decisions).toEqual({ approved: 2, returned: 1, rejected: 1, total: 4 });
    expect(view.candidates).toMatchObject({
      decided: 3,
      approvedWithoutEdits: 1,
      acceptance: "33%",
      explained:
        "1 of the 3 rule candidates analysts decided were approved without an edit: the share of the extraction's drafts that needed no change (ADR-006's measure).",
    });
    expect(view.median).toBe("1 h 30 min");
    expect(view.oldestSince).toBe("1 May 2000, 10:00 am IST");
  });
});
