import type { identity } from "@compliancewatch/contracts/openapi";

/**
 * RFC 9457 problem details, the body of every error response a service returns
 * (`py_common.problems`). Every committed spec publishes the same `Problem` and
 * `ValidationIssue` schemas, which types.test.ts checks, so the identity spec's generated
 * types stand for all of them.
 *
 * `type` is a URN, `urn:compliancewatch:problem:<slug>`, or `about:blank` for a plain HTTP
 * error; `correlation_id` echoes the x-request-id the caller sent; `errors` is present on a
 * 422 and names each failed field by its `loc`. Fields left null by the service are absent
 * from the body.
 */
export type Problem = identity.components["schemas"]["Problem"];

export type ValidationIssue = identity.components["schemas"]["ValidationIssue"];
