// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { SERVICE_NAMES } from "@/shared/config/services";
import { fakeFetch, hangingFetch, refusingFetch, textResponse } from "@/test/fake-fetch";
import { REQUEST_ID_HEADER } from "./api/client";
import { resetEnvCache } from "./env";
import {
  HEALTH_TIMEOUT_MS,
  probeAllHealth,
  probeAllReady,
  probeHealth,
  probeReady,
} from "./health";

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

function clock(...times: number[]): () => number {
  let index = 0;
  return () => times[Math.min(index++, times.length - 1)] as number;
}

describe("probeHealth", () => {
  it("reports a service that answers its health route as up, with its version and latency", async () => {
    const fake = fakeFetch([
      {
        method: "GET",
        path: "/health",
        body: { status: "ok", service: "rulebook", version: "0.1.0" },
      },
    ]);
    const probe = await probeHealth("rulebook", { fetchImpl: fake.fetchImpl, now: clock(10, 25) });
    expect(probe).toEqual({
      service: "rulebook",
      baseUrl: "http://localhost:8003",
      state: "up",
      status: 200,
      version: "0.1.0",
      latencyMs: 15,
    });
    const request = fake.requests[0];
    expect(request?.url).toBe("http://localhost:8003/health");
    expect(request?.headers[REQUEST_ID_HEADER]).toMatch(/^[0-9a-f-]{36}$/);
    expect(request?.headers["x-tenant-id"]).toBeUndefined();
    expect(request?.headers["x-cw-write-token"]).toBeUndefined();
    expect(request?.cache).toBe("no-store");
  });

  it("probes the base URL the environment names", async () => {
    vi.stubEnv("CW_WEB_EVAL_URL", "http://localhost:9209/");
    const fake = fakeFetch([{ path: "/health", body: { status: "ok", version: "1" } }]);
    const probe = await probeHealth("eval", { fetchImpl: fake.fetchImpl });
    expect(probe.baseUrl).toBe("http://localhost:9209");
    expect(fake.requests[0]?.url).toBe("http://localhost:9209/health");
  });

  it("counts an error status as down with the status as the reason", async () => {
    const fake = fakeFetch([{ path: "/health", status: 503, problem: { title: "Down" } }]);
    const probe = await probeHealth("qa", { fetchImpl: fake.fetchImpl });
    expect(probe).toMatchObject({ state: "down", status: 503, reason: "HTTP 503" });
    expect(probe.version).toBeUndefined();
  });

  it("counts a body that is not a health report as down", async () => {
    const fake = fakeFetch(() => textResponse(200, "hello"));
    expect(await probeHealth("qa", { fetchImpl: fake.fetchImpl })).toMatchObject({
      state: "down",
      status: 200,
      reason: "the answer is not a health report",
    });
    const odd = fakeFetch([{ path: "/health", body: { status: "starting" } }]);
    expect((await probeHealth("qa", { fetchImpl: odd.fetchImpl })).state).toBe("down");
  });

  it("keeps an answer without a version up", async () => {
    const fake = fakeFetch([{ path: "/health", body: { status: "ok" } }]);
    const probe = await probeHealth("pipeline", { fetchImpl: fake.fetchImpl });
    expect(probe.state).toBe("up");
    expect(probe).not.toHaveProperty("version");
  });

  it("counts a refused connection as unreachable", async () => {
    const probe = await probeHealth("identity", { fetchImpl: refusingFetch().fetchImpl });
    expect(probe).toMatchObject({ state: "down", reason: "unreachable" });
    expect(probe.status).toBeUndefined();
  });

  it("gives up after the time limit", async () => {
    const probe = await probeHealth("profile", {
      fetchImpl: hangingFetch().fetchImpl,
      timeoutMs: 5,
    });
    expect(probe).toMatchObject({ state: "down", reason: "no answer within 5 ms" });
    expect(HEALTH_TIMEOUT_MS).toBe(2_000);
  });
});

describe("probeAllHealth", () => {
  it("probes every service in the Makefile order and keeps going past a stopped one", async () => {
    const fake = fakeFetch((request) =>
      request.url.startsWith("http://localhost:8009")
        ? Promise.reject(new TypeError("fetch failed"))
        : new Response(JSON.stringify({ status: "ok", version: "0.1.0" }), {
            headers: { "content-type": "application/json" },
          }),
    );
    const probes = await probeAllHealth({ fetchImpl: fake.fetchImpl });
    expect(probes.map((probe) => probe.service)).toEqual([...SERVICE_NAMES]);
    expect(probes.filter((probe) => probe.state === "down").map((probe) => probe.service)).toEqual([
      "eval",
    ]);
  });
});

describe("probeReady", () => {
  it("reports a ready service with its checks", async () => {
    const fake = fakeFetch([
      { path: "/ready", body: { status: "ready", checks: { database: true, broker: true } } },
    ]);
    const probe = await probeReady("rulebook", { fetchImpl: fake.fetchImpl, now: clock(5, 9) });
    expect(probe).toEqual({
      service: "rulebook",
      baseUrl: "http://localhost:8003",
      state: "ready",
      status: 200,
      checks: { database: true, broker: true },
      latencyMs: 4,
    });
    expect(fake.requests[0]?.url).toBe("http://localhost:8003/ready");
    expect(fake.requests[0]?.headers["x-tenant-id"]).toBeUndefined();
    expect(fake.requests[0]?.cache).toBe("no-store");
  });

  it("reports a 503 readiness report as not ready, with the failing check", async () => {
    const fake = fakeFetch([
      {
        path: "/ready",
        status: 503,
        body: { status: "not_ready", checks: { database: false } },
      },
    ]);
    const probe = await probeReady("profile", { fetchImpl: fake.fetchImpl });
    expect(probe).toMatchObject({ state: "not_ready", status: 503, checks: { database: false } });
    expect(probe.reason).toBeUndefined();
  });

  it("counts another status, a body that is not a report and no answer as down", async () => {
    const teapot = fakeFetch([{ path: "/ready", status: 418, problem: { title: "Example" } }]);
    expect(await probeReady("qa", { fetchImpl: teapot.fetchImpl })).toMatchObject({
      state: "down",
      status: 418,
      reason: "HTTP 418",
      checks: {},
    });
    const odd = fakeFetch([{ path: "/ready", body: { status: "ready", checks: { a: "yes" } } }]);
    expect(await probeReady("qa", { fetchImpl: odd.fetchImpl })).toMatchObject({
      state: "down",
      reason: "the answer is not a readiness report",
    });
    const text = fakeFetch(() => textResponse(503, "busy"));
    expect((await probeReady("qa", { fetchImpl: text.fetchImpl })).state).toBe("down");
    const refused = await probeReady("eval", { fetchImpl: refusingFetch().fetchImpl });
    expect(refused).toMatchObject({ state: "down", reason: "unreachable" });
  });

  it("gives up after its time limit", async () => {
    const probe = await probeReady("eval", { fetchImpl: hangingFetch().fetchImpl, timeoutMs: 20 });
    expect(probe).toMatchObject({ state: "down", reason: "no answer within 20 ms" });
  });

  it("probes every service in the Makefile's order", async () => {
    const fake = fakeFetch([{ path: "/ready", body: { status: "ready", checks: {} } }]);
    const probes = await probeAllReady({ fetchImpl: fake.fetchImpl });
    expect(probes.map((probe) => probe.service)).toEqual([...SERVICE_NAMES]);
    expect(probes.every((probe) => probe.state === "ready")).toBe(true);
  });
});
