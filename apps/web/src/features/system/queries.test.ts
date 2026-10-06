// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetEnvCache } from "@/server/env";
import { resetFlagReader } from "@/server/flags";
import { fakeFetch, jsonResponse } from "@/test/fake-fetch";
import { getSystem } from "./queries";

afterEach(async () => {
  vi.unstubAllEnvs();
  resetEnvCache();
  await resetFlagReader();
});

describe("getSystem", () => {
  it("probes every service twice, counts them and says which tokens are set, never their values", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_AUTH_PROVIDER", "fake");
    vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", "example-review-token");
    const fake = fakeFetch((request) => {
      const port = new URL(request.url).port;
      if (port === "8009")
        return jsonResponse(503, { status: "not_ready", checks: { database: false } });
      return request.pathname === "/health"
        ? jsonResponse(200, { status: "ok", service: "example", version: "0.0.1" })
        : jsonResponse(200, { status: "ready", checks: { database: true } });
    });
    const system = await getSystem({ fetchImpl: fake.fetchImpl, env: {} });
    expect(fake.requests).toHaveLength(20);
    expect(system.summary).toEqual({ total: 10, up: 9, ready: 9 });
    expect(system.rows.find((row) => row.service === "eval")?.reason).toBe("HTTP 503");
    expect(system.facts).toMatchObject({
      environment: "test",
      authProvider: "fake",
      writeToken: false,
      reviewToken: true,
      flagProvider: { ok: true, name: "env" },
      telemetry: { enabled: false, exporting: false },
    });
    expect(JSON.stringify(system)).not.toContain("example-review-token");
    expect(system.probeTimeoutSeconds).toBe(2);
  });
});
