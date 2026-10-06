import "server-only";

import { PROBLEM_TYPE_PREFIX } from "@/entities/problem/mappers";
import type { ValidationIssue } from "@/entities/problem/types";
import type { ApiError } from "../result";

/**
 * The answers of the web app's own handlers (the BFF routes under /api-bff) when they refuse:
 * RFC 9457 problems in the services' shape, `application/problem+json` with the type, a plain
 * title, the status, a detail, the correlation id of the service call when there was one, and a
 * 422's `errors`, so a page reads a handler's refusal as it reads a service's. A refusal the
 * handler decides itself is typed `web-<slug>`; a service's passes on with its own type.
 */
export const PROBLEM_CONTENT_TYPE = "application/problem+json";

export interface HandlerProblem {
  /** The slug after `urn:compliancewatch:problem:`. */
  slug: string;
  status: number;
  title: string;
  detail?: string;
  correlationId?: string;
  errors?: readonly ValidationIssue[];
  /** Extension members (RFC 9457 section 3.2), such as the id of a document that was stored. */
  extensions?: Readonly<Record<string, unknown>>;
}

/** Never stored by a browser or a proxy: a refusal is about this request and this session. */
const NO_STORE = "private, no-store";

export function problemResponse(problem: HandlerProblem): Response {
  const body: Record<string, unknown> = {
    ...problem.extensions,
    type: `${PROBLEM_TYPE_PREFIX}${problem.slug}`,
    title: problem.title,
    status: problem.status,
  };
  if (problem.detail !== undefined) body.detail = problem.detail;
  if (problem.correlationId !== undefined && problem.correlationId !== "") {
    body.correlation_id = problem.correlationId;
  }
  if (problem.errors !== undefined && problem.errors.length > 0) body.errors = problem.errors;
  return new Response(JSON.stringify(body), {
    status: problem.status,
    headers: { "content-type": PROBLEM_CONTENT_TYPE, "cache-control": NO_STORE },
  });
}

/** The slug of a service problem's type, or the web slug for the kind of failure. */
function slugOf(error: ApiError): string {
  const type = error.problem?.type;
  if (type !== undefined && type.startsWith(PROBLEM_TYPE_PREFIX)) {
    return type.slice(PROBLEM_TYPE_PREFIX.length);
  }
  return `web-${error.kind.replace(/_/g, "-")}`;
}

/**
 * A service call's failure as the handler's answer: the status the service gave (502 when none
 * arrived), its type, the title and detail given here or the service's, the request id the call
 * sent as the correlation id, and a 422's errors.
 */
export function apiErrorResponse(
  error: ApiError,
  wording: { title?: string; detail?: string } = {},
  extensions?: Readonly<Record<string, unknown>>,
): Response {
  const detail = wording.detail ?? error.problem?.detail ?? undefined;
  return problemResponse({
    slug: slugOf(error),
    status: error.status ?? 502,
    title: wording.title ?? error.message,
    ...(detail === undefined || detail === null ? {} : { detail }),
    correlationId: error.requestId,
    ...(error.problem?.errors === undefined || error.problem.errors === null
      ? {}
      : { errors: error.problem.errors }),
    ...(extensions === undefined ? {} : { extensions }),
  });
}
