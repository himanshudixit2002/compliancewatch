import { describe, expect, it } from "vitest";
import {
  BACKFILL_STATUSES,
  backfillCounts,
  backfillStatusLabel,
  backfillStatusTone,
  type BackfillJob,
} from "./backfill";

function job(overrides: Partial<BackfillJob> = {}): BackfillJob {
  return {
    id: "bf_1",
    name: "Applicability decisions",
    service: "applicability-engine",
    status: "running",
    processed: 10,
    total: 20,
    startedAt: "2026-10-02T04:00:00Z",
    finishedAt: null,
    ...overrides,
  };
}

describe("backfill labels and tones", () => {
  it("words and tones every status", () => {
    expect(BACKFILL_STATUSES.map(backfillStatusLabel)).toEqual([
      "Pending",
      "Running",
      "Completed",
      "Failed",
    ]);
    expect(BACKFILL_STATUSES.map(backfillStatusTone)).toEqual([
      "neutral",
      "info",
      "success",
      "danger",
    ]);
  });
});

describe("backfillCounts", () => {
  it("counts every job and each status", () => {
    expect(
      backfillCounts([
        job(),
        job({ id: "2", status: "pending" }),
        job({ id: "3", status: "completed" }),
        job({ id: "4", status: "completed" }),
        job({ id: "5", status: "failed" }),
      ]),
    ).toEqual({ total: 5, pending: 1, running: 1, completed: 2, failed: 1 });
    expect(backfillCounts([])).toEqual({
      total: 0,
      pending: 0,
      running: 0,
      completed: 0,
      failed: 0,
    });
  });
});
