import { describe, expect, it } from "vitest";
import { PROBLEM_TYPE_PREFIX, fieldErrorsFromIssues, isProblemOf, problemSlug } from "./mappers";

describe("problemSlug", () => {
  it("extracts the slug of a ComplianceWatch problem type", () => {
    expect(problemSlug({ type: `${PROBLEM_TYPE_PREFIX}auth-token-invalid` })).toBe(
      "auth-token-invalid",
    );
  });

  it("gives null for a plain HTTP error, a foreign type, an empty slug or no problem", () => {
    expect(problemSlug({ type: "about:blank" })).toBeNull();
    expect(problemSlug({ type: "https://example.test/problems/x" })).toBeNull();
    expect(problemSlug({ type: PROBLEM_TYPE_PREFIX })).toBeNull();
    expect(problemSlug(null)).toBeNull();
    expect(problemSlug(undefined)).toBeNull();
  });
});

describe("isProblemOf", () => {
  it("matches by slug only", () => {
    const problem = { type: `${PROBLEM_TYPE_PREFIX}identity-mfa-required` };
    expect(isProblemOf(problem, "identity-mfa-required")).toBe(true);
    expect(isProblemOf(problem, "mfa-required")).toBe(false);
    expect(isProblemOf({ type: "about:blank" }, "about:blank")).toBe(false);
  });
});

describe("fieldErrorsFromIssues", () => {
  it("drops the loc root, joins the rest with dots and keeps messages per field in order", () => {
    expect(
      fieldErrorsFromIssues([
        { loc: ["body", "gstin"], msg: "Not a GSTIN", type: "value_error" },
        { loc: ["body", "gstin"], msg: "Too short", type: "string_too_short" },
        { loc: ["body", "changes", 0, "value"], msg: "Required", type: "missing" },
        { loc: ["query", "fy"], msg: "Bad year", type: "value_error" },
        { loc: ["path", "node_id"], msg: "Not a UUID", type: "uuid_parsing" },
        { loc: ["header", "x-tenant-id"], msg: "Required", type: "missing" },
      ]),
    ).toEqual({
      gstin: ["Not a GSTIN", "Too short"],
      "changes.0.value": ["Required"],
      fy: ["Bad year"],
      node_id: ["Not a UUID"],
      "x-tenant-id": ["Required"],
    });
  });

  it("keeps a bare root and a field without a root as they are", () => {
    expect(
      fieldErrorsFromIssues([
        { loc: ["body"], msg: "Expected an object", type: "model_type" },
        { loc: ["name"], msg: "Required", type: "missing" },
      ]),
    ).toEqual({ body: ["Expected an object"], name: ["Required"] });
  });

  it("gives an empty table for no issues", () => {
    expect(fieldErrorsFromIssues(null)).toEqual({});
    expect(fieldErrorsFromIssues(undefined)).toEqual({});
    expect(fieldErrorsFromIssues([])).toEqual({});
  });
});
