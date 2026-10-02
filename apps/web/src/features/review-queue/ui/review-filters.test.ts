import { describe, expect, it } from "vitest";
import { ALL, filterReviewItems, type ReviewRow } from "./review-filters";

function row(overrides: Partial<ReviewRow>): ReviewRow {
  return {
    id: "1",
    title: "Turnover band changed",
    description: "",
    href: "/admin/review/1",
    type: "attribute_change",
    typeLabel: "Attribute change",
    status: "pending",
    statusLabel: "Pending",
    statusTone: "warning",
    priorityLabel: "High",
    priorityTone: "danger",
    businessName: "Acme Traders",
    submittedBy: "Asha",
    submittedAt: "10 Apr 2026",
    ...overrides,
  };
}

const ROWS = [
  row({ id: "1" }),
  row({ id: "2", title: "Consent withdrawn", type: "consent_change", businessName: "Beta Foods" }),
  row({ id: "3", status: "approved", type: "evidence_review", businessName: "Beta Foods" }),
];

const ids = (rows: readonly ReviewRow[]) => rows.map((r) => r.id);

describe("filterReviewItems", () => {
  it("keeps every row for all statuses, all types and no search", () => {
    expect(ids(filterReviewItems(ROWS, { status: ALL, type: ALL, search: "" }))).toEqual([
      "1",
      "2",
      "3",
    ]);
  });

  it("narrows by status and type", () => {
    expect(ids(filterReviewItems(ROWS, { status: "pending", type: ALL, search: "" }))).toEqual([
      "1",
      "2",
    ]);
    expect(
      ids(filterReviewItems(ROWS, { status: "pending", type: "consent_change", search: "" })),
    ).toEqual(["2"]);
  });

  it("searches the title and the business ignoring case", () => {
    expect(ids(filterReviewItems(ROWS, { status: ALL, type: ALL, search: " BETA " }))).toEqual([
      "2",
      "3",
    ]);
    expect(ids(filterReviewItems(ROWS, { status: ALL, type: ALL, search: "consent" }))).toEqual([
      "2",
    ]);
  });
});
