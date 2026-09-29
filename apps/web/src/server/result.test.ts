// @vitest-environment node
import { describe, expect, it } from "vitest";
import { PROBLEM_TYPE_PREFIX } from "@/entities/problem/mappers";
import {
  defaultMessageFor,
  err,
  isProblem,
  mapResult,
  ok,
  toActionProblem,
  toActionState,
  unwrapOr,
  type ApiError,
  type ApiErrorKind,
} from "./result";

const REQUEST_ID = "0f0c7f2e-8d31-4c58-9c2b-0b7b6b9d9e01";

function apiError(overrides: Partial<ApiError> = {}): ApiError {
  return {
    kind: "server",
    status: 500,
    requestId: REQUEST_ID,
    message: defaultMessageFor("server"),
    ...overrides,
  };
}

describe("Result", () => {
  it("wraps a value with an optional request id", () => {
    expect(ok(1)).toEqual({ ok: true, value: 1 });
    expect(ok("x", REQUEST_ID)).toEqual({ ok: true, value: "x", requestId: REQUEST_ID });
    expect(err(apiError())).toEqual({ ok: false, error: apiError() });
  });

  it("maps a value and keeps an error", () => {
    expect(mapResult(ok(2, REQUEST_ID), (n) => n * 2)).toEqual({
      ok: true,
      value: 4,
      requestId: REQUEST_ID,
    });
    const failure = err(apiError());
    expect(mapResult(failure, (n: number) => n * 2)).toBe(failure);
  });

  it("unwraps with a fallback", () => {
    expect(unwrapOr(ok([1]), [])).toEqual([1]);
    expect(unwrapOr(err(apiError()), [])).toEqual([]);
  });
});

describe("isProblem", () => {
  it("matches the problem slug and nothing without a problem", () => {
    const error = apiError({
      kind: "forbidden",
      status: 403,
      problem: { type: `${PROBLEM_TYPE_PREFIX}identity-mfa-required`, title: "MFA", status: 403 },
    });
    expect(isProblem(error, "identity-mfa-required")).toBe(true);
    expect(isProblem(error, "auth-token-invalid")).toBe(false);
    expect(isProblem(apiError({ kind: "network", status: undefined }), "x")).toBe(false);
  });
});

describe("defaultMessageFor", () => {
  it("has a sentence for every kind", () => {
    const kinds: ApiErrorKind[] = [
      "unauthenticated",
      "payment_required",
      "forbidden",
      "not_found",
      "conflict",
      "too_large",
      "unsupported_media",
      "validation",
      "rate_limited",
      "unavailable",
      "server",
      "bad_request",
      "network",
    ];
    for (const kind of kinds) expect(defaultMessageFor(kind)).toMatch(/\S+\./);
  });
});

describe("toActionProblem", () => {
  it("passes the service's problem through with the request id as the correlation id", () => {
    const error = apiError({
      kind: "conflict",
      status: 409,
      problem: {
        type: `${PROBLEM_TYPE_PREFIX}document-exists`,
        title: "Document exists",
        detail: "metadata_differs",
        status: 409,
      },
    });
    expect(toActionProblem(error)).toEqual({
      type: `${PROBLEM_TYPE_PREFIX}document-exists`,
      title: "Document exists",
      detail: "metadata_differs",
      correlationId: REQUEST_ID,
    });
  });

  it("synthesises a web-local problem when no body arrived", () => {
    const error = apiError({ kind: "network", status: undefined, message: "Down" });
    expect(toActionProblem(error)).toEqual({
      type: `${PROBLEM_TYPE_PREFIX}web-network`,
      title: "Down",
      correlationId: REQUEST_ID,
    });
    expect(toActionProblem(apiError({ kind: "rate_limited" })).type).toBe(
      `${PROBLEM_TYPE_PREFIX}web-rate-limited`,
    );
  });

  it("drops a null detail", () => {
    const error = apiError({
      problem: { type: "about:blank", title: "Internal Server Error", detail: null, status: 500 },
    });
    expect(toActionProblem(error)).toEqual({
      type: "about:blank",
      title: "Internal Server Error",
      correlationId: REQUEST_ID,
    });
  });
});

describe("toActionState", () => {
  it("turns a success into ok with the value and an optional message", () => {
    expect(toActionState(ok({ id: 1 }))).toEqual({ status: "ok", value: { id: 1 } });
    expect(toActionState(ok(undefined), { message: "Saved" })).toEqual({
      status: "ok",
      value: undefined,
      message: "Saved",
    });
  });

  it("turns a failure into error with the problem and any field errors", () => {
    const validation = apiError({
      kind: "validation",
      status: 422,
      fieldErrors: { gstin: ["Not a GSTIN"] },
      problem: {
        type: `${PROBLEM_TYPE_PREFIX}request-invalid`,
        title: "Request is invalid",
        status: 422,
      },
    });
    expect(toActionState(err(validation))).toEqual({
      status: "error",
      problem: {
        type: `${PROBLEM_TYPE_PREFIX}request-invalid`,
        title: "Request is invalid",
        correlationId: REQUEST_ID,
      },
      fieldErrors: { gstin: ["Not a GSTIN"] },
    });
    expect(toActionState(err(apiError({ fieldErrors: {} })))).toEqual({
      status: "error",
      problem: {
        type: `${PROBLEM_TYPE_PREFIX}web-server`,
        title: defaultMessageFor("server"),
        correlationId: REQUEST_ID,
      },
    });
  });
});
