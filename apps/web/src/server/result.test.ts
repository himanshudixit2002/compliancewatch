// @vitest-environment node
import { describe, expect, it } from "vitest";
import { PROBLEM_TYPE_PREFIX } from "@/entities/problem/mappers";
import {
  defaultMessageFor,
  err,
  isProblem,
  mapBody,
  mapResult,
  ok,
  statusForKind,
  toActionProblem,
  toActionState,
  unwrapOr,
  webError,
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

  it("maps a body, and reports a success without one as a server error with its request id", () => {
    expect(mapBody(ok<number | undefined>(2, REQUEST_ID), (n) => n + 1)).toEqual({
      ok: true,
      value: 3,
      requestId: REQUEST_ID,
    });
    const failure = err(apiError());
    expect(mapBody(failure, (n: number) => n)).toBe(failure);
    const empty = mapBody(ok<number | undefined>(undefined, REQUEST_ID), (n) => n);
    expect(empty.ok).toBe(false);
    if (!empty.ok) {
      expect(empty.error).toMatchObject({ kind: "server", status: 500, requestId: REQUEST_ID });
      expect(isProblem(empty.error, "web-empty-body")).toBe(true);
    }
    const anonymous = mapBody(ok<number | undefined>(undefined), (n) => n);
    expect(!anonymous.ok && anonymous.error.requestId).toBe("");
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
      "precondition_required",
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

describe("webError", () => {
  it("builds a web-local problem with the status of its kind and no request id", () => {
    const error = webError(
      "unavailable",
      "web-auth-provider-missing",
      "Sign-in is not configured",
      "Set CW_WEB_AUTH_PROVIDER.",
    );
    expect(error).toEqual({
      kind: "unavailable",
      status: 503,
      requestId: "",
      message: "Sign-in is not configured",
      problem: {
        type: `${PROBLEM_TYPE_PREFIX}web-auth-provider-missing`,
        title: "Sign-in is not configured",
        status: 503,
        detail: "Set CW_WEB_AUTH_PROVIDER.",
      },
    });
    expect(isProblem(error, "web-auth-provider-missing")).toBe(true);
  });

  it("carries field errors for a validation failure and drops an empty map", () => {
    const invalid = webError("validation", "web-form-invalid", "Check the form", undefined, {
      roles: ["Choose at least one role."],
    });
    expect(invalid.status).toBe(422);
    expect(invalid.fieldErrors).toEqual({ roles: ["Choose at least one role."] });
    expect(invalid.problem).not.toHaveProperty("detail");
    expect(webError("forbidden", "web-x", "No", undefined, {})).not.toHaveProperty("fieldErrors");
    expect(toActionState(err(invalid))).toEqual({
      status: "error",
      problem: {
        type: `${PROBLEM_TYPE_PREFIX}web-form-invalid`,
        title: "Check the form",
        correlationId: "",
      },
      fieldErrors: { roles: ["Choose at least one role."] },
    });
  });

  it("maps every kind to its status, and network to none", () => {
    const expected: Record<ApiErrorKind, number | undefined> = {
      unauthenticated: 401,
      payment_required: 402,
      forbidden: 403,
      not_found: 404,
      conflict: 409,
      too_large: 413,
      unsupported_media: 415,
      validation: 422,
      precondition_required: 428,
      rate_limited: 429,
      unavailable: 503,
      server: 500,
      bad_request: 400,
      network: undefined,
    };
    for (const [kind, status] of Object.entries(expected)) {
      expect(statusForKind(kind as ApiErrorKind), kind).toBe(status);
    }
  });
});
