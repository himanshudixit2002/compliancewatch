import type { Problem } from "./types";

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
