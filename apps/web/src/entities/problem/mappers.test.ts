import { describe, expect, it } from "vitest";
import { PROBLEM_TYPE_PREFIX, isProblemOf, problemSlug } from "./mappers";

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
