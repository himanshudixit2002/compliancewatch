import { describe, expect, it } from "vitest";
import {
  PIPELINE_RUN_STATUSES,
  formatDuration,
  pipelineCounts,
  runDurationSeconds,
  runStatusLabel,
  runStatusTone,
  type PipelineRun,
} from "./pipeline";

function run(overrides: Partial<PipelineRun> = {}): PipelineRun {
  return {
    id: "run_1",
    name: "Example circulars",
    stage: "fetch",
    status: "running",
    processed: 10,
    total: 20,
    startedAt: "2000-10-02T04:00:00Z",
    finishedAt: null,
    error: null,
    ...overrides,
  };
}

describe("run labels and tones", () => {
  it("words and tones every status, the ones to watch first", () => {
    expect(PIPELINE_RUN_STATUSES).toEqual(["running", "failed", "pending", "completed"]);
    expect(PIPELINE_RUN_STATUSES.map(runStatusLabel)).toEqual([
      "Running",
      "Failed",
      "Pending",
      "Completed",
    ]);
    expect(PIPELINE_RUN_STATUSES.map(runStatusTone)).toEqual([
      "info",
      "danger",
      "neutral",
      "success",
    ]);
  });
});

describe("pipelineCounts", () => {
  it("counts every run and each status", () => {
    expect(
      pipelineCounts([
        run(),
        run({ id: "2", status: "failed" }),
        run({ id: "3", status: "failed" }),
        run({ id: "4", status: "completed" }),
      ]),
    ).toEqual({ total: 4, pending: 0, running: 1, completed: 1, failed: 2 });
  });
});

describe("runDurationSeconds", () => {
  it("measures from start to finish in whole seconds", () => {
    expect(
      runDurationSeconds({
        startedAt: "2000-10-02T04:00:00Z",
        finishedAt: "2000-10-02T04:12:05.4Z",
      }),
    ).toBe(725);
  });

  it("has no duration until the run has started and finished, and never a negative one", () => {
    expect(runDurationSeconds({ startedAt: null, finishedAt: null })).toBeNull();
    expect(runDurationSeconds({ startedAt: "2000-10-02T04:00:00Z", finishedAt: null })).toBeNull();
    expect(
      runDurationSeconds({ startedAt: "2000-10-02T04:00:00Z", finishedAt: "2000-10-02T03:59:00Z" }),
    ).toBe(0);
  });
});

describe("formatDuration", () => {
  it("words seconds, minutes and hours", () => {
    expect(formatDuration(0)).toBe("0 s");
    expect(formatDuration(59)).toBe("59 s");
    expect(formatDuration(60)).toBe("1 min 0 s");
    expect(formatDuration(725)).toBe("12 min 5 s");
    expect(formatDuration(3599)).toBe("59 min 59 s");
    expect(formatDuration(3600)).toBe("1 h 0 min");
    expect(formatDuration(7440)).toBe("2 h 4 min");
  });
});
