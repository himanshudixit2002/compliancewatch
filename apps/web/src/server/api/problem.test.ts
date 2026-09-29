// @vitest-environment node
import { describe, expect, it } from "vitest";
import { PROBLEM_TYPE_PREFIX } from "@/entities/problem/mappers";
import { problemResponse, textResponse } from "@/test/fake-fetch";
import { defaultMessageFor } from "../result";
import {
  PROBLEM_MEDIA_TYPE,
  fieldErrorsFromIssues,
  kindForStatus,
  networkError,
  parseProblem,
  problemFromBody,
  retryAfterSeconds,
  toApiError,
} from "./problem";

const REQUEST_ID = "7a3b1c2d-0e4f-4a5b-8c6d-9e0f1a2b3c4d";

describe("kindForStatus", () => {
  it("maps every documented status and falls back by class", () => {
    expect(kindForStatus(401)).toBe("unauthenticated");
    expect(kindForStatus(402)).toBe("payment_required");
    expect(kindForStatus(403)).toBe("forbidden");
    expect(kindForStatus(404)).toBe("not_found");
    expect(kindForStatus(409)).toBe("conflict");
    expect(kindForStatus(413)).toBe("too_large");
    expect(kindForStatus(415)).toBe("unsupported_media");
    expect(kindForStatus(422)).toBe("validation");
    expect(kindForStatus(428)).toBe("precondition_required");
    expect(kindForStatus(429)).toBe("rate_limited");
    expect(kindForStatus(503)).toBe("unavailable");
    expect(kindForStatus(500)).toBe("server");
    expect(kindForStatus(502)).toBe("server");
    expect(kindForStatus(400)).toBe("bad_request");
    expect(kindForStatus(410)).toBe("bad_request");
    expect(kindForStatus(301)).toBe("server");
  });
});

describe("problemFromBody", () => {
  it("accepts a problem body and keeps only the known optional fields", () => {
    expect(
      problemFromBody({
        type: `${PROBLEM_TYPE_PREFIX}node-not-found`,
        title: "Node not found",
        status: 404,
        detail: "no node 1",
        instance: "/v1/profile/nodes/1",
        correlation_id: REQUEST_ID,
        extra: "ignored",
      }),
    ).toEqual({
      type: `${PROBLEM_TYPE_PREFIX}node-not-found`,
      title: "Node not found",
      status: 404,
      detail: "no node 1",
      instance: "/v1/profile/nodes/1",
      correlation_id: REQUEST_ID,
    });
  });

  it("keeps well-formed issues and drops malformed ones", () => {
    const problem = problemFromBody({
      type: "t",
      title: "Invalid",
      status: 422,
      errors: [{ loc: ["body", "x"], msg: "Required", type: "missing" }, { msg: "no loc" }, 3],
    });
    expect(problem?.errors).toEqual([{ loc: ["body", "x"], msg: "Required", type: "missing" }]);
  });

  it("rejects anything that is not a problem", () => {
    expect(problemFromBody(null)).toBeNull();
    expect(problemFromBody("Bad Gateway")).toBeNull();
    expect(problemFromBody([1])).toBeNull();
    expect(problemFromBody({ message: "boom" })).toBeNull();
    expect(problemFromBody({ type: "t", title: "x", status: "500" })).toBeNull();
  });
});

describe("parseProblem", () => {
  it("reads a JSON body once and answers null for other content or a consumed body", async () => {
    const response = problemResponse(409, { title: "Exists" });
    expect(response.headers.get("content-type")).toBe(PROBLEM_MEDIA_TYPE);
    const problem = await parseProblem(response);
    expect(problem?.title).toBe("Exists");
    expect(await parseProblem(response)).toBeNull();
    expect(await parseProblem(textResponse(502, "Bad Gateway"))).toBeNull();
    expect(
      await parseProblem(
        new Response("{not json", { status: 500, headers: { "content-type": "application/json" } }),
      ),
    ).toBeNull();
    expect(await parseProblem(new Response("x", { status: 500 }))).toBeNull();
  });
});

describe("retryAfterSeconds", () => {
  it("reads a delay in seconds, an HTTP date, and nothing else", () => {
    expect(retryAfterSeconds(new Headers({ "retry-after": "30" }))).toBe(30);
    expect(retryAfterSeconds(new Headers({ "retry-after": " 5 " }))).toBe(5);
    const now = Date.parse("2026-09-29T10:00:00Z");
    expect(
      retryAfterSeconds(new Headers({ "retry-after": "Tue, 29 Sep 2026 10:00:45 GMT" }), () => now),
    ).toBe(45);
    expect(
      retryAfterSeconds(new Headers({ "retry-after": "Tue, 29 Sep 2026 09:00:00 GMT" }), () => now),
    ).toBe(0);
    expect(retryAfterSeconds(new Headers({ "retry-after": "soon" }))).toBeUndefined();
    expect(retryAfterSeconds(new Headers({ "retry-after": "" }))).toBeUndefined();
    expect(retryAfterSeconds(new Headers())).toBeUndefined();
  });
});

describe("toApiError", () => {
  it("uses the problem's title as the message and carries the problem", () => {
    const problem = { type: "about:blank", title: "Not Found", status: 404 };
    expect(
      toApiError({ status: 404, headers: new Headers(), problem, requestId: REQUEST_ID }),
    ).toEqual({
      kind: "not_found",
      status: 404,
      requestId: REQUEST_ID,
      message: "Not Found",
      problem,
    });
  });

  it("falls back to the default message without a problem body", () => {
    expect(
      toApiError({ status: 502, headers: new Headers(), problem: null, requestId: REQUEST_ID }),
    ).toEqual({
      kind: "server",
      status: 502,
      requestId: REQUEST_ID,
      message: defaultMessageFor("server"),
    });
  });

  it("adds retry seconds on a 429 and field errors on a 422", () => {
    expect(
      toApiError({
        status: 429,
        headers: new Headers({ "retry-after": "12" }),
        problem: null,
        requestId: REQUEST_ID,
      }).retryAfterSeconds,
    ).toBe(12);
    const validation = toApiError({
      status: 422,
      headers: new Headers(),
      problem: {
        type: `${PROBLEM_TYPE_PREFIX}request-invalid`,
        title: "Request is invalid",
        status: 422,
        errors: [
          { loc: ["body", "gstin"], msg: "Not a GSTIN", type: "value_error" },
          { loc: ["body", "changes", 0, "value"], msg: "Required", type: "missing" },
        ],
      },
      requestId: REQUEST_ID,
    });
    expect(validation.kind).toBe("validation");
    expect(validation.fieldErrors).toEqual({
      gstin: ["Not a GSTIN"],
      "changes.0.value": ["Required"],
    });
    expect(fieldErrorsFromIssues(validation.problem?.errors)).toEqual(validation.fieldErrors);
    const bare = toApiError({
      status: 422,
      headers: new Headers(),
      problem: { type: "t", title: "Invalid", status: 422 },
      requestId: REQUEST_ID,
    });
    expect(bare.fieldErrors).toBeUndefined();
  });
});

describe("networkError", () => {
  it("names a timeout and treats everything else as unreachable", () => {
    const timeout = new DOMException("The operation was aborted due to timeout", "TimeoutError");
    expect(networkError(REQUEST_ID, timeout, 250)).toEqual({
      kind: "network",
      requestId: REQUEST_ID,
      message: "The service did not answer within 250 ms.",
    });
    expect(networkError(REQUEST_ID, timeout).message).toBe("The service did not answer in time.");
    expect(networkError(REQUEST_ID, new TypeError("fetch failed"))).toEqual({
      kind: "network",
      requestId: REQUEST_ID,
      message: defaultMessageFor("network"),
    });
  });
});
