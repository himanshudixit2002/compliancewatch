// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { TENANT_HEADER, WRITE_TOKEN_HEADER } from "@/server/api/client";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { fakeFetch } from "@/test/fake-fetch";
import { COUNT_PAGE, adminCountsGateway } from "./gateway";

const analyst: ClientPrincipal = {
  userId: "user-analyst",
  tenantId: "00000000-0000-4000-8000-00000000000a",
  tenantKind: "internal",
  roles: ["analyst"],
};

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

function group(name: string, openCount: number) {
  return { entity_type: "form", proposed_name: name, open_count: openCount, examples: [] };
}

describe("AdminCountsGateway", () => {
  it("counts the open entity groups and the mentions in them from one fresh page", async () => {
    const fake = fakeFetch([
      {
        method: "GET",
        path: "/v1/rulebook/review/entities",
        body: [group("Example form one", 2), group("Example form two", 3)],
      },
    ]);
    const count = await adminCountsGateway({
      session: analyst,
      fetchImpl: fake.fetchImpl,
    }).entityGroups();
    expect(count).toMatchObject({ ok: true, value: { count: 2, capped: false, within: 5 } });
    const request = fake.requests[0];
    expect(request?.url).toBe(
      `http://localhost:8003/v1/rulebook/review/entities?limit=${COUNT_PAGE}`,
    );
    expect(request?.cache).toBe("no-store");
    expect(request?.headers[TENANT_HEADER]).toBeUndefined();
    expect(request?.headers[WRITE_TOKEN_HEADER]).toBeUndefined();
  });

  it("marks a full page of open relation candidates as capped", async () => {
    const rows = Array.from({ length: COUNT_PAGE }, (_, index) => ({
      candidate_id: String(index),
    }));
    const fake = fakeFetch([{ method: "GET", path: "/v1/rulebook/review/relations", body: rows }]);
    const count = await adminCountsGateway({
      session: analyst,
      fetchImpl: fake.fetchImpl,
    }).openRelationCandidates();
    expect(count).toMatchObject({ ok: true, value: { count: COUNT_PAGE, capped: true } });
    expect(new URL(fake.requests[0]?.url ?? "").searchParams.toString()).toBe(
      "status=open&limit=200",
    );
  });

  it("counts the rules and the prompts through their cached global reads", async () => {
    const fake = fakeFetch([
      { method: "GET", path: "/v1/rulebook/rules", body: [{ rule_key: "a" }, { rule_key: "b" }] },
      { method: "GET", path: "/v1/llm-gateway/prompts", body: [{ name: "example.prompt" }] },
    ]);
    const gateway = adminCountsGateway({ session: analyst, fetchImpl: fake.fetchImpl });
    expect(await gateway.rules()).toMatchObject({ ok: true, value: { count: 2, capped: false } });
    expect(await gateway.prompts()).toMatchObject({ ok: true, value: { count: 1, capped: false } });
    expect(fake.requests.map((request) => request.next)).toEqual([
      { revalidate: 300, tags: ["rulebook:rules"] },
      { revalidate: 300, tags: ["llm-gateway:prompts"] },
    ]);
    expect(fake.requests[1]?.url).toBe("http://localhost:8008/v1/llm-gateway/prompts");
  });

  it("passes a failed read on as the error", async () => {
    const fake = fakeFetch([
      { path: "/v1/rulebook/rules", status: 503, problem: { title: "Rulebook unavailable" } },
    ]);
    const rules = await adminCountsGateway({ session: analyst, fetchImpl: fake.fetchImpl }).rules();
    expect(rules).toMatchObject({
      ok: false,
      error: { kind: "unavailable", message: "Rulebook unavailable" },
    });
  });
});
