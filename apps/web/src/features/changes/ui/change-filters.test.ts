import { describe, expect, it } from "vitest";
import { ALL, NO_CHANGE_FILTERS, filterChanges, type ChangeRow } from "./change-filters";

function row(overrides: Partial<ChangeRow>): ChangeRow {
  return {
    id: "1",
    title: "GST return due date moved",
    regulator: "CBIC",
    summary: "",
    href: "/changes/1",
    applicability: "applies",
    applicabilityLabel: "Applies to you",
    applicabilityTone: "success",
    reviewStatus: "published",
    reviewLabel: "Published",
    reviewTone: "success",
    facts: [],
    categories: [],
    ...overrides,
  };
}

const ROWS = [
  row({ id: "1" }),
  row({ id: "2", title: "TDS rate change", regulator: "CBDT", applicability: "pending" }),
  row({ id: "3", title: "Labour code", regulator: "MoLE", reviewStatus: "in_review" }),
];

const ids = (rows: readonly ChangeRow[]) => rows.map((r) => r.id);

describe("filterChanges", () => {
  it("keeps every row with no filters", () => {
    expect(ids(filterChanges(ROWS, NO_CHANGE_FILTERS))).toEqual(["1", "2", "3"]);
  });

  it("searches the title and the regulator, ignoring case and outer spaces", () => {
    expect(ids(filterChanges(ROWS, { ...NO_CHANGE_FILTERS, search: "  tds " }))).toEqual(["2"]);
    expect(ids(filterChanges(ROWS, { ...NO_CHANGE_FILTERS, search: "mole" }))).toEqual(["3"]);
    expect(filterChanges(ROWS, { ...NO_CHANGE_FILTERS, search: "nothing" })).toEqual([]);
  });

  it("narrows by applicability and by review status together", () => {
    expect(
      ids(filterChanges(ROWS, { search: "", applicability: "applies", reviewStatus: ALL })),
    ).toEqual(["1", "3"]);
    expect(
      ids(filterChanges(ROWS, { search: "", applicability: "applies", reviewStatus: "in_review" })),
    ).toEqual(["3"]);
  });
});
