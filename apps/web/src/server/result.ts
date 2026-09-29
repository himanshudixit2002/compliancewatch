import "server-only";

import { PROBLEM_TYPE_PREFIX, isProblemOf } from "@/entities/problem/mappers";
import type { Problem } from "@/entities/problem/types";
import type { ActionProblem, ActionState, FieldErrors } from "@/shared/lib/action-state";

/**
 * How the server layer reports the outcome of a service call. A query or a gateway method
 * returns `Result<T>`: the value, or an `ApiError` that says what kind of failure it was, with
 * the problem the service sent and the request id to quote to support. Expected failures are
 * values, never exceptions; a page renders `ErrorState` from the error and a server action maps
 * it to an `ActionState` with `toActionState`.
 *
 * Kinds, by the status the service answered (server/api/problem.ts does the mapping):
 *   401 unauthenticated   403 forbidden        404 not_found      409 conflict
 *   402 payment_required  413 too_large        415 unsupported_media
 *   422 validation (with fieldErrors from errors[].loc)            429 rate_limited
 *   503 unavailable       other 5xx server     other 4xx bad_request
 *   no response (refused connection, timeout, DNS) network
 */
export type ApiErrorKind =
  | "unauthenticated"
  | "payment_required"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "too_large"
  | "unsupported_media"
  | "validation"
  | "rate_limited"
  | "unavailable"
  | "server"
  | "bad_request"
  | "network";

export interface ApiError {
  kind: ApiErrorKind;
  /** The HTTP status; absent when no response arrived. */
  status?: number;
  /** The parsed problem body, when the service sent one. */
  problem?: Problem;
  /** The x-request-id the call sent; the service echoes it as the problem's correlation_id. */
  requestId: string;
  /** From Retry-After on a 429 or 503. */
  retryAfterSeconds?: number;
  /** Field paths to messages, from a 422's errors[].loc. */
  fieldErrors?: FieldErrors;
  /** One line for people: the problem's title, or a default for the kind. */
  message: string;
}

export interface Ok<T> {
  ok: true;
  value: T;
  /** The x-request-id the call sent, for logging. */
  requestId?: string;
}

export interface Err<E> {
  ok: false;
  error: E;
}

export type Result<T, E = ApiError> = Ok<T> | Err<E>;

export function ok<T>(value: T, requestId?: string): Ok<T> {
  return requestId === undefined ? { ok: true, value } : { ok: true, value, requestId };
}

export function err<E>(error: E): Err<E> {
  return { ok: false, error };
}

export function mapResult<T, U, E>(result: Result<T, E>, fn: (value: T) => U): Result<U, E> {
  return result.ok ? { ...result, value: fn(result.value) } : result;
}

export function unwrapOr<T, E>(result: Result<T, E>, fallback: T): T {
  return result.ok ? result.value : fallback;
}

/** True when the error carries the named problem (`isProblem(error, "identity-mfa-required")`). */
export function isProblem(error: ApiError, slug: string): boolean {
  return isProblemOf(error.problem, slug);
}

const DEFAULT_MESSAGES: Record<ApiErrorKind, string> = {
  unauthenticated: "Your session is not valid here. Sign in again.",
  payment_required: "This needs a plan that includes it.",
  forbidden: "You do not have access to this.",
  not_found: "This was not found.",
  conflict: "This conflicts with the current state. Reload and try again.",
  too_large: "This is too large to send.",
  unsupported_media: "This file type is not accepted.",
  validation: "Some fields need attention.",
  rate_limited: "Too many requests. Wait a moment and try again.",
  unavailable: "The service is not available right now.",
  server: "The service reported an error.",
  bad_request: "The request was refused.",
  network: "The service could not be reached.",
};

export function defaultMessageFor(kind: ApiErrorKind): string {
  return DEFAULT_MESSAGES[kind];
}

const STATUS_BY_KIND: Readonly<Record<Exclude<ApiErrorKind, "network">, number>> = {
  unauthenticated: 401,
  payment_required: 402,
  forbidden: 403,
  not_found: 404,
  conflict: 409,
  too_large: 413,
  unsupported_media: 415,
  validation: 422,
  rate_limited: 429,
  unavailable: 503,
  server: 500,
  bad_request: 400,
};

/** The status a kind stands for; none for a failure without a response. */
export function statusForKind(kind: ApiErrorKind): number | undefined {
  return kind === "network" ? undefined : STATUS_BY_KIND[kind];
}

/**
 * An ApiError decided in the web layer before any request: a missing configuration, a refused
 * role, a form that fails a check the server layer owns. It carries a web-local problem
 * (`urn:compliancewatch:problem:web-<slug>`) and no request id, since no service was called.
 */
export function webError(
  kind: Exclude<ApiErrorKind, "network">,
  slug: string,
  title: string,
  detail?: string,
  fieldErrors?: FieldErrors,
): ApiError {
  const status = STATUS_BY_KIND[kind];
  const problem: Problem = { type: `${PROBLEM_TYPE_PREFIX}${slug}`, title, status };
  if (detail !== undefined) problem.detail = detail;
  const error: ApiError = { kind, status, requestId: "", problem, message: title };
  if (fieldErrors !== undefined && Object.keys(fieldErrors).length > 0) {
    error.fieldErrors = fieldErrors;
  }
  return error;
}

/** The problem a form shows: the service's, or a web-local one for a failure without a body. */
export function toActionProblem(error: ApiError): ActionProblem {
  const { problem } = error;
  const type = problem?.type ?? `${PROBLEM_TYPE_PREFIX}web-${error.kind.replace(/_/g, "-")}`;
  const detail = problem?.detail ?? undefined;
  return {
    type,
    title: problem?.title ?? error.message,
    ...(detail === undefined ? {} : { detail }),
    correlationId: error.requestId,
  };
}

/** Maps a service Result to what a server action returns to its form. */
export function toActionState<T>(
  result: Result<T>,
  options: { message?: string } = {},
): ActionState<T> {
  if (result.ok) {
    return options.message === undefined
      ? { status: "ok", value: result.value }
      : { status: "ok", value: result.value, message: options.message };
  }
  const { fieldErrors } = result.error;
  return {
    status: "error",
    problem: toActionProblem(result.error),
    ...(fieldErrors !== undefined && Object.keys(fieldErrors).length > 0 ? { fieldErrors } : {}),
  };
}
