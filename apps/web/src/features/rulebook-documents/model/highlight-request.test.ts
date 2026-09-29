import { describe, expect, it } from "vitest";
import { parseHighlightRequest } from "./highlight-request";

const CLAUSE = "00000000-0000-5000-8000-0000000000c1";

describe("parseHighlightRequest", () => {
  it("asks for nothing without the parameters", () => {
    expect(parseHighlightRequest({})).toBeNull();
    expect(parseHighlightRequest({ other: "1" })).toBeNull();
  });

  it("asks for a whole clause, or a span in it", () => {
    expect(parseHighlightRequest({ clause_id: CLAUSE })).toEqual({ clauseId: CLAUSE });
    expect(
      parseHighlightRequest({ clause_id: CLAUSE.toUpperCase(), start: "3", end: "12" }),
    ).toEqual({ clauseId: CLAUSE, span: { start: 3, end: 12 } });
  });

  it("calls a malformed link invalid rather than ignoring it", () => {
    for (const params of [
      { clause_id: "not-a-uuid" },
      { start: "1", end: "2" },
      { clause_id: CLAUSE, start: "1" },
      { clause_id: CLAUSE, end: "2" },
      { clause_id: CLAUSE, start: "-1", end: "2" },
      { clause_id: CLAUSE, start: "1.5", end: "2" },
      { clause_id: [CLAUSE, CLAUSE] },
      { clause_id: CLAUSE, start: "1", end: "99999999" },
    ]) {
      expect(parseHighlightRequest(params), JSON.stringify(params)).toBe("invalid");
    }
  });
});
