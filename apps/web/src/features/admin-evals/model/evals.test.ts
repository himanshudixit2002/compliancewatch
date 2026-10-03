import { describe, expect, it } from "vitest";
import {
  EVAL_RUN_STATUSES,
  evalSummary,
  runStatusLabel,
  runStatusTone,
  scorePercent,
  sortRuns,
  type EvalRun,
} from "./evals";

function run(overrides: Partial<EvalRun> = {}): EvalRun {
  return {
    id: "run_1",
    name: "Extraction, nightly",
    model: "claude-sonnet-4-5",
    status: "passed",
    score: 0.92,
    startedAt: "2026-10-02T21:00:00Z",
    ...overrides,
  };
}

describe("run labels and tones", () => {
  it("words and tones every status", () => {
    expect(EVAL_RUN_STATUSES.map(runStatusLabel)).toEqual(["Running", "Passed", "Failed"]);
    expect(EVAL_RUN_STATUSES.map(runStatusTone)).toEqual(["info", "success", "danger"]);
  });
});

describe("scorePercent", () => {
  it("rounds a score to a whole percentage and keeps a missing one missing", () => {
    expect(scorePercent(0)).toBe(0);
    expect(scorePercent(0.874)).toBe(87);
    expect(scorePercent(0.875)).toBe(88);
    expect(scorePercent(1)).toBe(100);
    expect(scorePercent(null)).toBeNull();
  });
});

describe("sortRuns", () => {
  it("puts the newest run first and leaves the given list as it was", () => {
    const runs = [
      run({ id: "old", startedAt: "2026-09-30T21:00:00Z" }),
      run({ id: "new", startedAt: "2026-10-02T21:00:00Z" }),
      run({ id: "middle", startedAt: "2026-10-02T02:00:00+05:30" }),
    ];
    expect(sortRuns(runs).map((entry) => entry.id)).toEqual(["new", "middle", "old"]);
    expect(runs.map((entry) => entry.id)).toEqual(["old", "new", "middle"]);
  });
});

describe("evalSummary", () => {
  it("counts the runs and averages the scores of those that have one", () => {
    expect(
      evalSummary([
        run({ score: 0.9 }),
        run({ id: "2", status: "failed", score: 0.62 }),
        run({ id: "3", status: "running", score: null }),
      ]),
    ).toEqual({ total: 3, passed: 1, failed: 1, scored: 2, averageScore: 76 });
  });

  it("has no average before any run has a score", () => {
    expect(evalSummary([run({ status: "running", score: null })]).averageScore).toBeNull();
    expect(evalSummary([])).toEqual({
      total: 0,
      passed: 0,
      failed: 0,
      scored: 0,
      averageScore: null,
    });
  });
});
