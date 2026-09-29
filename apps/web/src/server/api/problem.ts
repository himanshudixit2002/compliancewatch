import "server-only";

import { fieldErrorsFromIssues } from "@/entities/problem/mappers";
import type { Problem, ValidationIssue } from "@/entities/problem/types";
import { defaultMessageFor, type ApiError, type ApiErrorKind } from "../result";

/**
 * RFC 9457 problem parsing: every non-2xx a service answers becomes an `ApiError` whose kind
 * follows the status, with the problem body when there is one (a proxy or a crashed process
 * may answer plain text, which is tolerated) and the field errors of a 422.
 */
export const PROBLEM_MEDIA_TYPE = "application/problem+json";

export { fieldErrorsFromIssues };

const KIND_BY_STATUS: Readonly<Record<number, ApiErrorKind>> = {
  401: "unauthenticated",
  402: "payment_required",
  403: "forbidden",
  404: "not_found",
  409: "conflict",
  413: "too_large",
  415: "unsupported_media",
  422: "validation",
  429: "rate_limited",
  503: "unavailable",
};

export function kindForStatus(status: number): ApiErrorKind {
  const known = KIND_BY_STATUS[status];
  if (known !== undefined) return known;
  if (status >= 500) return "server";
  if (status >= 400) return "bad_request";
  return "server";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isIssue(value: unknown): value is ValidationIssue {
  return (
    isRecord(value) &&
    Array.isArray(value.loc) &&
    typeof value.msg === "string" &&
    typeof value.type === "string"
  );
}

/** A Problem from an already-parsed body, or null when the body is not one. */
export function problemFromBody(body: unknown): Problem | null {
  if (!isRecord(body)) return null;
  const { type, title, status, detail, instance, correlation_id: correlationId, errors } = body;
  if (typeof type !== "string" || typeof title !== "string" || typeof status !== "number") {
    return null;
  }
  const problem: Problem = { type, title, status };
  if (typeof detail === "string") problem.detail = detail;
  if (typeof instance === "string") problem.instance = instance;
  if (typeof correlationId === "string") problem.correlation_id = correlationId;
  if (Array.isArray(errors)) problem.errors = errors.filter(isIssue);
  return problem;
}

/**
 * Reads a response body as a Problem when its content type is JSON and the body has not been
 * consumed (openapi-fetch consumes it; `call` passes the parsed body to `problemFromBody`).
 */
export async function parseProblem(response: Response): Promise<Problem | null> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!/json/i.test(contentType) || response.bodyUsed) return null;
  try {
    return problemFromBody(JSON.parse(await response.text()));
  } catch {
    return null;
  }
}

/** Retry-After as seconds from now, whether the header is a delay or an HTTP date. */
export function retryAfterSeconds(
  headers: Headers,
  now: () => number = Date.now,
): number | undefined {
  const value = headers.get("retry-after");
  if (value === null || value.trim() === "") return undefined;
  if (/^\d+$/.test(value.trim())) return Number(value.trim());
  const at = Date.parse(value);
  if (Number.isNaN(at)) return undefined;
  return Math.max(0, Math.ceil((at - now()) / 1000));
}

export interface ErrorResponseInput {
  status: number;
  headers: Headers;
  problem: Problem | null;
  requestId: string;
}

/** The ApiError for a non-2xx response. */
export function toApiError(input: ErrorResponseInput): ApiError {
  const { status, headers, problem, requestId } = input;
  const kind = kindForStatus(status);
  const error: ApiError = {
    kind,
    status,
    requestId,
    message: problem?.title ?? defaultMessageFor(kind),
  };
  if (problem !== null) error.problem = problem;
  const retry = retryAfterSeconds(headers);
  if (retry !== undefined) error.retryAfterSeconds = retry;
  if (kind === "validation") {
    const fieldErrors = fieldErrorsFromIssues(problem?.errors);
    if (Object.keys(fieldErrors).length > 0) error.fieldErrors = fieldErrors;
  }
  return error;
}

/** The ApiError when no response arrived: refused connection, DNS failure or the timeout. */
export function networkError(requestId: string, cause: unknown, timeoutMs?: number): ApiError {
  const timedOut = cause instanceof Error && cause.name === "TimeoutError";
  const message =
    timedOut && timeoutMs !== undefined
      ? `The service did not answer within ${timeoutMs} ms.`
      : timedOut
        ? "The service did not answer in time."
        : defaultMessageFor("network");
  return { kind: "network", requestId, message };
}
