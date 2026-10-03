import { describe, expect, it } from "vitest";
import {
  TRIAGE_PRIORITIES,
  TRIAGE_REASONS,
  TRIAGE_STATUSES,
  sortTriageItems,
  triageCounts,
  triagePriorityLabel,
  triagePriorityTone,
  triageReasonLabel,
  triageReasonOptions,
  triageStatusLabel,
  triageStatusOptions,
  triageStatusTone,
  type TriageItem,
} from "./qa-triage";

function item(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    id: "tri_1",
    question: "When is GSTR-3B due for March?",
    category: "GST returns",
    reason: "not_covered",
    priority: "medium",
    status: "open",
    assignee: null,
    createdAt: "2026-10-01T05:00:00Z",
    ...overrides,
  };
}

describe("triage labels and tones", () => {
  it("words and tones every status", () => {
    expect(TRIAGE_STATUSES.map(triageStatusLabel)).toEqual(["Open", "Closed"]);
    expect(TRIAGE_STATUSES.map(triageStatusTone)).toEqual(["warning", "success"]);
    expect(triageStatusOptions()).toEqual([
      { value: "open", label: "Open" },
      { value: "closed", label: "Closed" },
    ]);
  });

  it("words every reason", () => {
    expect(TRIAGE_REASONS.map(triageReasonLabel)).toEqual(["Not covered", "Marked unhelpful"]);
    expect(triageReasonOptions().map((option) => option.value)).toEqual(TRIAGE_REASONS);
  });

  it("words and tones every priority", () => {
    expect(TRIAGE_PRIORITIES.map(triagePriorityLabel)).toEqual(["High", "Medium", "Low"]);
    expect(TRIAGE_PRIORITIES.map(triagePriorityTone)).toEqual(["danger", "warning", "neutral"]);
  });
});

describe("sortTriageItems", () => {
  it("puts open items first, then the higher priority, then the one that has waited longest", () => {
    const items = [
      item({ id: "closed-high", status: "closed", priority: "high" }),
      item({ id: "open-low", priority: "low" }),
      item({ id: "open-high-new", priority: "high", createdAt: "2026-10-02T05:00:00Z" }),
      item({ id: "open-high-old", priority: "high", createdAt: "2026-10-02T09:00:00+05:30" }),
      item({ id: "open-medium" }),
      item({ id: "closed-low", status: "closed", priority: "low" }),
    ];
    expect(sortTriageItems(items).map((entry) => entry.id)).toEqual([
      "open-high-old",
      "open-high-new",
      "open-medium",
      "open-low",
      "closed-high",
      "closed-low",
    ]);
  });

  it("returns a new list and leaves the given one as it was", () => {
    const items = [item({ id: "a", status: "closed" }), item({ id: "b" })];
    expect(sortTriageItems(items).map((entry) => entry.id)).toEqual(["b", "a"]);
    expect(items.map((entry) => entry.id)).toEqual(["a", "b"]);
  });
});

describe("triageCounts", () => {
  it("counts every item, the open ones and the closed ones", () => {
    expect(triageCounts([item(), item({ id: "2" }), item({ id: "3", status: "closed" })])).toEqual({
      total: 3,
      open: 2,
      closed: 1,
    });
    expect(triageCounts([])).toEqual({ total: 0, open: 0, closed: 0 });
  });
});
