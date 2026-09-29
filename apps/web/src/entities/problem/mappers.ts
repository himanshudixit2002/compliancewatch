import type { Problem, ValidationIssue } from "./types";

/** Every service names its errors `urn:compliancewatch:problem:<slug>` (domain_kernel.errors). */
export const PROBLEM_TYPE_PREFIX = "urn:compliancewatch:problem:";

/**
 * The slug of a problem's type: "urn:compliancewatch:problem:auth-token-invalid" gives
 * "auth-token-invalid". A plain HTTP error ("about:blank") or a foreign type gives null.
 */
export function problemSlug(problem: Pick<Problem, "type"> | null | undefined): string | null {
  const type = problem?.type;
  if (type === undefined || !type.startsWith(PROBLEM_TYPE_PREFIX)) return null;
  const slug = type.slice(PROBLEM_TYPE_PREFIX.length);
  return slug === "" ? null : slug;
}

/** True when the problem is the named one, by slug. */
export function isProblemOf(
  problem: Pick<Problem, "type"> | null | undefined,
  slug: string,
): boolean {
  return problemSlug(problem) === slug;
}

/** The first element of a FastAPI `loc`: where the value came from, not part of the field name. */
const LOC_ROOTS = new Set(["body", "query", "header", "path", "cookie"]);

/**
 * Field errors from a 422's issues: `["body", "gstin"]` becomes `gstin`,
 * `["body", "changes", 0, "value"]` becomes `changes.0.value`, and a bare `["body"]` stays `body`.
 * Messages for the same field are kept in order.
 */
export function fieldErrorsFromIssues(
  issues: readonly ValidationIssue[] | null | undefined,
): Readonly<Record<string, readonly string[]>> {
  const errors: Record<string, string[]> = {};
  for (const issue of issues ?? []) {
    const parts = issue.loc.map(String);
    const [root] = parts;
    if (parts.length > 1 && root !== undefined && LOC_ROOTS.has(root)) parts.shift();
    const key = parts.join(".");
    (errors[key] ??= []).push(issue.msg);
  }
  return errors;
}
