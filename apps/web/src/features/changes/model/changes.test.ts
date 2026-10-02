import { describe, expect, it } from "vitest";
import {
  CHANGE_APPLICABILITIES,
  CHANGE_REVIEW_STATUSES,
  SUMMARY_LIMIT,
  applicabilityLabel,
  applicabilityOptions,
  applicabilityTone,
  changeCounts,
  changeFacts,
  reviewStatusLabel,
  reviewStatusOptions,
  reviewStatusTone,
  shortSummary,
  type ChangeItem,
} from "./changes";

function changeItem(overrides: Partial<ChangeItem> = {}): ChangeItem {
  return {
    id: "chg_1",
    title: "GST return due date moved",
    regulator: "CBIC",
    effectiveDate: "2026-04-01",
    publishedAt: "2026-03-10",
    applicability: "applies",
    confidence: 0.874,
    reviewStatus: "published",
    categories: ["GST"],
    supersedes: null,
    summary: "The GSTR-3B due date moves to the 22nd.",
    ...overrides,
  };
}

describe("change labels and tones", () => {
  it("words and tones every applicability", () => {
    expect(CHANGE_APPLICABILITIES.map(applicabilityLabel)).toEqual([
      "Applies to you",
      "Pending review",
      "Does not apply",
      "Not yet evaluated",
    ]);
    expect(CHANGE_APPLICABILITIES.map(applicabilityTone)).toEqual([
      "success",
      "warning",
      "neutral",
      "info",
    ]);
    expect(applicabilityOptions()[0]).toEqual({ value: "applies", label: "Applies to you" });
  });

  it("words and tones every review status", () => {
    expect(CHANGE_REVIEW_STATUSES.map(reviewStatusLabel)).toEqual([
      "Published",
      "In review",
      "Draft",
      "Rejected",
    ]);
    expect(CHANGE_REVIEW_STATUSES.map(reviewStatusTone)).toEqual([
      "success",
      "warning",
      "neutral",
      "danger",
    ]);
    expect(reviewStatusOptions().map((option) => option.value)).toEqual(CHANGE_REVIEW_STATUSES);
  });
});

describe("shortSummary", () => {
  it("keeps a summary up to the limit and cuts a longer one with an ellipsis", () => {
    const exact = "a".repeat(SUMMARY_LIMIT);
    expect(shortSummary(exact)).toBe(exact);
    const long = `${"word ".repeat(39)}word and more`;
    const cut = shortSummary(long);
    expect(cut.endsWith("…")).toBe(true);
    expect(cut.length).toBeLessThanOrEqual(SUMMARY_LIMIT + 1);
    expect(cut).not.toMatch(/\s…$/);
  });
});

describe("changeFacts", () => {
  it("names the regulator, the dates and the confidence as a whole percentage", () => {
    expect(changeFacts(changeItem())).toEqual([
      "From CBIC",
      "Effective 1 Apr 2026",
      "Published 10 Mar 2026",
      "Confidence 87%",
    ]);
  });

  it("adds what it supersedes and leaves out an unknown confidence", () => {
    expect(changeFacts(changeItem({ supersedes: "Old rule", confidence: null }))).toEqual([
      "From CBIC",
      "Effective 1 Apr 2026",
      "Published 10 Mar 2026",
      "Supersedes Old rule",
    ]);
  });
});

describe("changeCounts", () => {
  it("counts all changes, those that apply and those in review", () => {
    expect(
      changeCounts([
        changeItem(),
        changeItem({ id: "2", applicability: "pending", reviewStatus: "in_review" }),
        changeItem({ id: "3", applicability: "does_not_apply" }),
      ]),
    ).toEqual({ total: 3, applicable: 1, inReview: 1 });
    expect(changeCounts([])).toEqual({ total: 0, applicable: 0, inReview: 0 });
  });
});
