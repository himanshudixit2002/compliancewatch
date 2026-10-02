import { describe, expect, it } from "vitest";
import {
  REVIEW_ITEM_TYPES,
  REVIEW_STATUSES,
  reviewCounts,
  reviewPriorityLabel,
  reviewPriorityTone,
  reviewStatusLabel,
  reviewStatusTabs,
  reviewStatusTone,
  reviewTypeLabel,
  reviewTypeOptions,
  type ReviewItem,
  type ReviewPriority,
} from "./review-queue";

function item(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: "rev_1",
    type: "attribute_change",
    title: "Turnover band changed",
    description: "From 1-5 Cr to 5-20 Cr.",
    status: "pending",
    priority: "high",
    submittedBy: "Asha",
    submittedAt: "2026-04-10T12:00:00Z",
    businessName: "Acme Traders",
    ...overrides,
  };
}

const PRIORITIES: ReviewPriority[] = ["high", "medium", "low"];

describe("review labels and tones", () => {
  it("words and tones every status, type and priority", () => {
    expect(REVIEW_STATUSES.map(reviewStatusLabel)).toEqual(["Pending", "Approved", "Rejected"]);
    expect(REVIEW_STATUSES.map(reviewStatusTone)).toEqual(["warning", "success", "danger"]);
    expect(REVIEW_ITEM_TYPES.map(reviewTypeLabel)).toEqual([
      "Attribute change",
      "Obligation",
      "Evidence",
      "Consent",
    ]);
    expect(PRIORITIES.map(reviewPriorityLabel)).toEqual(["High", "Medium", "Low"]);
    expect(PRIORITIES.map(reviewPriorityTone)).toEqual(["danger", "warning", "neutral"]);
  });

  it("builds the status tabs with pending first, and the type options", () => {
    expect(reviewStatusTabs()[0]).toEqual({ value: "pending", label: "Pending" });
    expect(reviewTypeOptions().map((option) => option.value)).toEqual(REVIEW_ITEM_TYPES);
  });
});

describe("reviewCounts", () => {
  it("counts all items and each status", () => {
    expect(
      reviewCounts([
        item(),
        item({ id: "2" }),
        item({ id: "3", status: "approved" }),
        item({ id: "4", status: "rejected" }),
      ]),
    ).toEqual({ total: 4, pending: 2, approved: 1, rejected: 1 });
  });
});
