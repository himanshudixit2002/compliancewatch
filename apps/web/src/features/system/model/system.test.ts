import { describe, expect, it } from "vitest";
import { SCREENS, screenById } from "@/shared/config/screens";
import { SERVICE_NAMES } from "@/shared/config/services";
import { registryFacts, serviceRow, systemRows, type HealthLike, type ReadyLike } from "./system";

function health(service: string, overrides: Partial<HealthLike> = {}): HealthLike {
  return {
    service,
    baseUrl: `http://localhost:9000/${service}`,
    state: "up",
    status: 200,
    version: "0.0.1",
    latencyMs: 12,
    ...overrides,
  };
}

function ready(service: string, overrides: Partial<ReadyLike> = {}): ReadyLike {
  return {
    service,
    state: "ready",
    status: 200,
    checks: { database: true },
    latencyMs: 3,
    ...overrides,
  };
}

describe("registryFacts", () => {
  it("lists the live screens that call a service and the routes still awaited from it", () => {
    const facts = registryFacts("llm-gateway");
    expect(facts.liveScreens.map((screen) => screen.id)).toContain("admin.llm.prompts");
    expect(facts.liveScreens.find((screen) => screen.id === "admin.llm.prompts")?.href).toBe(
      "/admin/llm/prompts",
    );
    expect(facts.awaited.map((item) => `${item.method} ${item.path}`)).toContain(
      "PUT /v1/llm-gateway/prompts/{name}",
    );
  });

  it("links only a page without parameters and counts a route once", () => {
    const relation = screenById("admin.rulebook.relation");
    const facts = registryFacts("rulebook", [relation, { ...relation, id: "example.copy" }]);
    expect(facts.liveScreens.map((screen) => screen.href)).toEqual([null, null]);
    const waiting = { ...relation, status: "waiting" as const };
    expect(registryFacts("rulebook", [waiting]).liveScreens).toEqual([]);
  });
});

describe("serviceRow", () => {
  it("words a healthy, ready service with its checks", () => {
    const row = serviceRow(
      health("rulebook"),
      ready("rulebook", { checks: { broker: true, database: false } }),
    );
    expect(row).toMatchObject({
      service: "rulebook",
      up: true,
      healthLabel: "Up",
      version: "0.0.1",
      latency: "12 ms",
      ready: "ready",
      readyLabel: "Ready",
      checks: [
        { name: "broker", passed: true },
        { name: "database", passed: false },
      ],
      reason: null,
    });
  });

  it("gives the reason a service is down, and says when no readiness report came", () => {
    const row = serviceRow(
      health("eval", { state: "down", reason: "unreachable", version: undefined }),
      ready("eval", { state: "down", reason: "unreachable", checks: {} }),
    );
    expect(row).toMatchObject({
      up: false,
      healthLabel: "Down",
      version: null,
      readyLabel: "No readiness report",
      reason: "unreachable",
    });
    expect(serviceRow(health("qa"), ready("qa", { state: "not_ready" })).readyLabel).toBe(
      "Not ready",
    );
  });
});

describe("systemRows", () => {
  it("keeps the Makefile's order and counts the services up and ready", () => {
    const reversed = [...SERVICE_NAMES].reverse();
    const { rows, summary } = systemRows(
      reversed.map((service) => health(service, service === "qa" ? { state: "down" } : {})),
      reversed.map((service) => ready(service, service === "eval" ? { state: "not_ready" } : {})),
      SCREENS,
    );
    expect(rows.map((row) => row.service)).toEqual([...SERVICE_NAMES]);
    expect(summary).toEqual({ total: 10, up: 9, ready: 9 });
  });

  it("leaves out a service it has no probe for", () => {
    expect(systemRows([health("identity")], []).rows).toEqual([]);
  });
});
