import { describe, expect, it } from "vitest";
import { DISPATCH_FILTERS, filterDispatchRows, isDispatchFilter } from "./dispatch-rows";
import type { DispatchRow } from "./dispatch-rows";

function row(id: string, bucket: DispatchRow["bucket"]): DispatchRow {
  return {
    id,
    occasionLabel: "Reminder",
    channelLabel: "WhatsApp",
    recipient: "+919876543210",
    state: bucket,
    stateLabel: bucket,
    tone: "neutral",
    bucket,
    createdLabel: "1 Oct 2026",
  };
}

const ROWS = [row("a", "pending"), row("b", "delivered"), row("c", "failed"), row("d", "failed")];

describe("filterDispatchRows", () => {
  it("keeps every row for all", () => {
    expect(filterDispatchRows(ROWS, "all")).toBe(ROWS);
  });

  it("keeps the rows in one bucket", () => {
    expect(filterDispatchRows(ROWS, "pending").map((r) => r.id)).toEqual(["a"]);
    expect(filterDispatchRows(ROWS, "delivered").map((r) => r.id)).toEqual(["b"]);
    expect(filterDispatchRows(ROWS, "failed").map((r) => r.id)).toEqual(["c", "d"]);
  });
});

describe("isDispatchFilter", () => {
  it("accepts the listed filters only", () => {
    for (const filter of DISPATCH_FILTERS) expect(isDispatchFilter(filter)).toBe(true);
    expect(isDispatchFilter("")).toBe(false);
    expect(isDispatchFilter("bounced")).toBe(false);
  });
});
