import { afterEach, describe, expect, it, vi } from "vitest";
import {
  isPastDue,
  reviewTaskPriorityLabel,
  reviewTaskPriorityTone,
  reviewTaskStatusLabel,
  reviewTaskStatusTone,
  reviewTaskTypeLabel,
  type ReviewTask,
  type ReviewTaskPriority,
  type ReviewTaskStatus,
  type ReviewTaskType,
} from "./review-task";

const NOW = new Date("2026-10-15T06:30:00Z");

function task(overrides: Partial<ReviewTask> = {}): ReviewTask {
  return {
    id: "task_1",
    type: "obligation_review",
    status: "pending",
    priority: "high",
    assignee: null,
    title: "New TDS obligation",
    description: "The pipeline proposed a monthly TDS deposit.",
    createdAt: "2026-10-10T04:00:00Z",
    dueAt: "2026-10-14T12:30:00Z",
    metadata: {},
    ...overrides,
  };
}

const STATUSES: ReviewTaskStatus[] = ["pending", "approved", "rejected"];
const TYPES: ReviewTaskType[] = [
  "attribute_change",
  "obligation_review",
  "evidence_review",
  "consent_change",
];
const PRIORITIES: ReviewTaskPriority[] = ["high", "medium", "low"];

afterEach(() => {
  vi.useRealTimers();
});

describe("review task labels and tones", () => {
  it("words and tones every status, type and priority", () => {
    expect(STATUSES.map(reviewTaskStatusLabel)).toEqual(["Pending", "Approved", "Rejected"]);
    expect(STATUSES.map(reviewTaskStatusTone)).toEqual(["warning", "success", "danger"]);
    expect(TYPES.map(reviewTaskTypeLabel)).toEqual([
      "Attribute change",
      "Obligation review",
      "Evidence review",
      "Consent change",
    ]);
    expect(PRIORITIES.map(reviewTaskPriorityLabel)).toEqual(["High", "Medium", "Low"]);
    expect(PRIORITIES.map(reviewTaskPriorityTone)).toEqual(["danger", "warning", "neutral"]);
  });
});

describe("isPastDue", () => {
  it("is true for a pending task whose due time has passed", () => {
    expect(isPastDue(task(), NOW)).toBe(true);
  });

  it("is false before the due time, once decided and without a due time", () => {
    expect(isPastDue(task({ dueAt: "2026-10-16T12:30:00Z" }), NOW)).toBe(false);
    expect(isPastDue(task({ status: "approved" }), NOW)).toBe(false);
    expect(isPastDue(task({ status: "rejected" }), NOW)).toBe(false);
    expect(isPastDue(task({ dueAt: null }), NOW)).toBe(false);
  });

  it("measures against the current time by default", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    expect(isPastDue(task())).toBe(true);
    expect(isPastDue(task({ dueAt: "2026-10-15T07:00:00Z" }))).toBe(false);
  });
});
