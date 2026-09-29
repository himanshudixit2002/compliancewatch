// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { PROBLEM_TYPE_PREFIX } from "@/entities/problem/mappers";
import { fakeFetch, type FakeFetch } from "@/test/fake-fetch";
import { resetEnvCache } from "../env";
import { REQUEST_ID_HEADER, TENANT_HEADER, WRITE_TOKEN_HEADER, call } from "./client";
import {
  identityClient,
  llmGatewayClient,
  notificationClient,
  obligationClient,
  profileClient,
  qaClient,
  rulebookAdmin,
  rulebookClient,
  tenantIdOf,
  type ClientContext,
  type ClientPrincipal,
} from "./services";

const TENANT = "2a6f0c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b";
const OTHER_TENANT = "9b8a7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";

const owner: ClientPrincipal = {
  userId: "user-1",
  tenantId: TENANT,
  tenantKind: "business",
  roles: ["owner"],
};
const analyst: ClientPrincipal = {
  userId: "user-2",
  tenantId: "internal",
  tenantKind: "internal",
  roles: ["analyst"],
};

function ctx(session: ClientPrincipal | null, fake: FakeFetch, tenantId?: string): ClientContext {
  return tenantId === undefined
    ? { session, fetchImpl: fake.fetchImpl }
    : { session, fetchImpl: fake.fetchImpl, tenantId };
}

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("tenant-scoped clients", () => {
  it("send the session's tenant as x-tenant-id to every tenant-scoped service", async () => {
    const fake = fakeFetch(
      () => new Response("{}", { headers: { "content-type": "application/json" } }),
    );
    const c = ctx(owner, fake);
    await identityClient(c).GET("/v1/identity/billing/plans");
    await profileClient(c).GET("/v1/profile/ping");
    await notificationClient(c).GET("/v1/notification/templates");
    await llmGatewayClient(c).GET("/v1/llm-gateway/models");
    await obligationClient(c).GET("/v1/obligation/ping");
    await qaClient(c).GET("/v1/qa/ping");
    expect(fake.requests.map((request) => request.url)).toEqual([
      "http://localhost:8001/v1/identity/billing/plans",
      "http://localhost:8002/v1/profile/ping",
      "http://localhost:8006/v1/notification/templates",
      "http://localhost:8008/v1/llm-gateway/models",
      "http://localhost:8005/v1/obligation/ping",
      "http://localhost:8007/v1/qa/ping",
    ]);
    for (const request of fake.requests) {
      expect(request.headers[TENANT_HEADER]).toBe(TENANT);
      expect(request.headers[REQUEST_ID_HEADER]).toMatch(/^[0-9a-f-]{36}$/);
      expect(request.headers[WRITE_TOKEN_HEADER]).toBeUndefined();
    }
  });

  it("let an admin lookup act for another tenant through the context override only", async () => {
    const fake = fakeFetch([{ path: "/v1/profile/ping", body: {} }]);
    await profileClient(ctx(analyst, fake, OTHER_TENANT)).GET("/v1/profile/ping");
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBe(OTHER_TENANT);
    expect(tenantIdOf({ session: owner, tenantId: OTHER_TENANT })).toBe(OTHER_TENANT);
    expect(tenantIdOf({ session: owner })).toBe(TENANT);
    expect(tenantIdOf({ session: null })).toBeUndefined();
  });

  it("send no tenant header without a session", async () => {
    const fake = fakeFetch([{ path: "/v1/identity/billing/plans", body: [] }]);
    await identityClient(ctx(null, fake)).GET("/v1/identity/billing/plans");
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBeUndefined();
  });

  it("read the base URL and the time limit from the environment", async () => {
    vi.stubEnv("CW_WEB_PROFILE_URL", "http://localhost:9202/");
    vi.stubEnv("CW_WEB_REQUEST_TIMEOUT_MS", "20");
    const fake = fakeFetch([{ path: "/v1/profile/ping", body: {} }]);
    await profileClient(ctx(owner, fake)).GET("/v1/profile/ping");
    expect(fake.requests[0]?.url).toBe("http://localhost:9202/v1/profile/ping");
  });
});

describe("rulebookClient", () => {
  it("never sends a tenant header or the write token", async () => {
    const fake = fakeFetch([{ path: "/v1/rulebook/rules", body: [] }]);
    await rulebookClient({ fetchImpl: fake.fetchImpl }).GET("/v1/rulebook/rules");
    expect(fake.requests[0]?.url).toBe("http://localhost:8003/v1/rulebook/rules");
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBeUndefined();
    expect(fake.requests[0]?.headers[WRITE_TOKEN_HEADER]).toBeUndefined();
    expect(fake.requests[0]?.headers.accept).toBe("application/json");
  });
});

describe("rulebookAdmin", () => {
  it("refuses a session without a regulatory role, before any request", () => {
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", "local-write-token");
    const fake = fakeFetch([]);
    for (const session of [owner, null]) {
      const result = rulebookAdmin(ctx(session, fake));
      expect(result.ok).toBe(false);
      if (result.ok) throw new Error("expected an error");
      expect(result.error.kind).toBe("forbidden");
      expect(result.error.requestId).toBe("");
      expect(result.error.problem?.type).toBe(`${PROBLEM_TYPE_PREFIX}web-regulatory-role-required`);
    }
    expect(fake.requests).toHaveLength(0);
  });

  it("answers unavailable while the write token is not configured", () => {
    const result = rulebookAdmin(ctx(analyst, fakeFetch([])));
    expect(result).toMatchObject({
      ok: false,
      error: {
        kind: "unavailable",
        status: 503,
        message: "Rulebook writes are not configured",
        problem: { type: `${PROBLEM_TYPE_PREFIX}web-write-token-missing` },
      },
    });
  });

  it("attaches the write token, and no tenant header, for a regulatory session", async () => {
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", "local-write-token");
    const fake = fakeFetch([
      {
        method: "POST",
        path: "/v1/rulebook/review/entities/decisions",
        body: {
          entity_id: null,
          items_closed: 0,
          relation_targets_updated: 0,
          resolution: null,
          status: "rejected",
        },
      },
    ]);
    const admin = rulebookAdmin(ctx(analyst, fake, OTHER_TENANT));
    expect(admin.ok).toBe(true);
    if (!admin.ok) throw new Error("expected a client");
    const result = await call(
      admin.value.POST("/v1/rulebook/review/entities/decisions", {
        body: {
          decided_by: analyst.userId,
          decision: "reject",
          entity_type: "form",
          proposed_name: "example form",
          reject_reason: "not_an_entity",
        },
      }),
    );
    expect(result.ok).toBe(true);
    expect(fake.requests[0]?.headers[WRITE_TOKEN_HEADER]).toBe("local-write-token");
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBeUndefined();
    expect(fake.requests[0]?.body).toMatchObject({
      decided_by: analyst.userId,
      decision: "reject",
    });
  });
});
