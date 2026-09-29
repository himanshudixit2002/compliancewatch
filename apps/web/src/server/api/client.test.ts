// @vitest-environment node
import type { identity } from "@compliancewatch/contracts/openapi";
import { describe, expect, it } from "vitest";
import { PROBLEM_TYPE_PREFIX } from "@/entities/problem/mappers";
import { fakeFetch, hangingFetch, jsonResponse, refusingFetch } from "@/test/fake-fetch";
import { defaultMessageFor } from "../result";
import {
  NetworkFailure,
  REQUEST_ID_HEADER,
  call,
  createServiceClient,
  requestIdOf,
} from "./client";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const BASE = "http://localhost:8001";

function identityClient(fetchImpl: ReturnType<typeof fakeFetch>["fetchImpl"], timeoutMs = 1000) {
  return createServiceClient<identity.paths>({
    service: "identity",
    baseUrl: BASE,
    timeoutMs,
    fetchImpl,
    headers: { "x-tenant-id": "tenant-1" },
  });
}

describe("createServiceClient", () => {
  it("sends accept, the configured headers and a fresh x-request-id per request", async () => {
    const fake = fakeFetch([{ method: "GET", path: "/v1/identity/billing/plans", body: [] }]);
    const client = identityClient(fake.fetchImpl);
    await client.GET("/v1/identity/billing/plans");
    await client.GET("/v1/identity/billing/plans");
    expect(fake.requests).toHaveLength(2);
    const [first, second] = fake.requests;
    expect(first?.url).toBe(`${BASE}/v1/identity/billing/plans`);
    expect(first?.headers.accept).toBe("application/json");
    expect(first?.headers["x-tenant-id"]).toBe("tenant-1");
    expect(first?.headers[REQUEST_ID_HEADER]).toMatch(UUID);
    expect(second?.headers[REQUEST_ID_HEADER]).toMatch(UUID);
    expect(first?.headers[REQUEST_ID_HEADER]).not.toBe(second?.headers[REQUEST_ID_HEADER]);
  });

  it("serialises path, query and JSON bodies the way the spec describes them", async () => {
    const fake = fakeFetch([
      { method: "GET", path: "/v1/identity/consents", body: { subject: "s", purposes: [] } },
      { method: "POST", path: "/v1/identity/consents", status: 201, body: { id: "c1" } },
    ]);
    const client = identityClient(fake.fetchImpl);
    await client.GET("/v1/identity/consents", { params: { query: { subject: "owner 1" } } });
    await client.POST("/v1/identity/consents", {
      body: {
        subject: "owner-1",
        purpose: "terms",
        granted: true,
        source: "web_onboarding",
        notice_version: "0.1-draft",
      },
    });
    expect(fake.requests[0]?.url).toBe(`${BASE}/v1/identity/consents?subject=owner%201`);
    expect(fake.requests[1]?.headers["content-type"]).toBe("application/json");
    expect(fake.requests[1]?.body).toMatchObject({ purpose: "terms", granted: true });
  });

  it("aborts a request that outlives the time limit", async () => {
    const hanging = hangingFetch();
    const client = identityClient(hanging.fetchImpl, 20);
    await expect(client.GET("/v1/identity/billing/plans")).rejects.toBeInstanceOf(NetworkFailure);
  });
});

describe("call", () => {
  it("gives ok with the data and the request id for a 2xx", async () => {
    const plans = [{ id: "starter", name: "Starter", price_paise: 0 }];
    const fake = fakeFetch([{ method: "GET", path: "/v1/identity/billing/plans", body: plans }]);
    const result = await call(identityClient(fake.fetchImpl).GET("/v1/identity/billing/plans"));
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("expected ok");
    expect(result.value).toEqual(plans);
    expect(result.requestId).toBe(fake.requests[0]?.headers[REQUEST_ID_HEADER]);
  });

  it("gives ok with undefined for an empty 204", async () => {
    const fake = fakeFetch(() => jsonResponse(204, undefined));
    const result = await call(identityClient(fake.fetchImpl).GET("/v1/identity/billing/plans"));
    expect(result).toMatchObject({ ok: true, value: undefined });
  });

  it("maps a problem response to the ApiError for its status, with the request id we sent", async () => {
    const fake = fakeFetch([
      {
        method: "GET",
        path: "/v1/identity/billing/plans",
        status: 503,
        problem: {
          type: `${PROBLEM_TYPE_PREFIX}billing-not-connected`,
          title: "Billing is not connected",
        },
        headers: { "retry-after": "60" },
      },
    ]);
    const result = await call(identityClient(fake.fetchImpl).GET("/v1/identity/billing/plans"));
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected an error");
    expect(result.error.kind).toBe("unavailable");
    expect(result.error.status).toBe(503);
    expect(result.error.message).toBe("Billing is not connected");
    expect(result.error.retryAfterSeconds).toBe(60);
    expect(result.error.problem?.type).toBe(`${PROBLEM_TYPE_PREFIX}billing-not-connected`);
    expect(result.error.requestId).toBe(fake.requests[0]?.headers[REQUEST_ID_HEADER]);
  });

  it("turns a 422 into a validation error with field errors", async () => {
    const fake = fakeFetch([
      {
        method: "POST",
        path: "/v1/identity/consents",
        status: 422,
        problem: {
          type: `${PROBLEM_TYPE_PREFIX}request-invalid`,
          title: "Request is invalid",
          errors: [{ loc: ["body", "notice_version"], msg: "Field required", type: "missing" }],
        },
      },
    ]);
    const result = await call(
      identityClient(fake.fetchImpl).POST("/v1/identity/consents", {
        body: { subject: "s", purpose: "terms", granted: true, source: "web_onboarding" },
      }),
    );
    expect(result).toMatchObject({
      ok: false,
      error: { kind: "validation", fieldErrors: { notice_version: ["Field required"] } },
    });
  });

  it("keeps the status mapping when the body is not a problem", async () => {
    const fake = fakeFetch(
      () =>
        new Response("<html>Bad Gateway</html>", {
          status: 502,
          headers: { "content-type": "text/html" },
        }),
    );
    const result = await call(identityClient(fake.fetchImpl).GET("/v1/identity/billing/plans"));
    expect(result).toMatchObject({
      ok: false,
      error: { kind: "server", status: 502, message: defaultMessageFor("server") },
    });
    if (result.ok) throw new Error("expected an error");
    expect(result.error.problem).toBeUndefined();
  });

  it("reports a refused connection and a timeout as network errors with the request id", async () => {
    const refusing = refusingFetch();
    const refused = await call(
      identityClient(refusing.fetchImpl).GET("/v1/identity/billing/plans"),
    );
    expect(refused).toMatchObject({ ok: false, error: { kind: "network" } });
    if (refused.ok) throw new Error("expected an error");
    expect(refused.error.requestId).toBe(refusing.requests[0]?.headers[REQUEST_ID_HEADER]);
    expect(refused.error.status).toBeUndefined();

    const hanging = hangingFetch();
    const timedOut = await call(
      identityClient(hanging.fetchImpl, 20).GET("/v1/identity/billing/plans"),
    );
    expect(timedOut).toMatchObject({
      ok: false,
      error: { kind: "network", message: "The service did not answer within 20 ms." },
    });
  });

  it("lets an unexpected exception propagate", async () => {
    await expect(call(Promise.reject(new Error("bug")))).rejects.toThrow("bug");
  });
});

describe("requestIdOf", () => {
  it("falls back to the echoed header and then to an empty string", () => {
    const echoed = new Response(null, { status: 204, headers: { [REQUEST_ID_HEADER]: "abc" } });
    expect(requestIdOf(echoed)).toBe("abc");
    expect(requestIdOf(new Response(null, { status: 204 }))).toBe("");
  });
});
