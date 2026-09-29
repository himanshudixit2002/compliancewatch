// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { fakeFetch, jsonResponse, problemResponse } from "@/test/fake-fetch";
import { getAdminHome } from "./queries";

const admin: ClientPrincipal = {
  userId: "user-admin",
  tenantId: "00000000-0000-4000-8000-00000000000a",
  tenantKind: "internal",
  roles: ["admin"],
};

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("getAdminHome", () => {
  it("reads every count and probes every service, and one stopped service fails only its parts", async () => {
    vi.stubEnv("CW_WEB_LLM_GATEWAY_URL", "http://localhost:9208");
    const fake = fakeFetch((request) => {
      if (request.url.startsWith("http://localhost:9208")) {
        return Promise.reject(new TypeError("fetch failed"));
      }
      if (request.pathname === "/health") return jsonResponse(200, { status: "ok", version: "1" });
      if (request.pathname === "/v1/rulebook/review/entities") {
        return jsonResponse(200, [
          { entity_type: "form", proposed_name: "Example", open_count: 4, examples: [] },
        ]);
      }
      if (request.pathname === "/v1/rulebook/review/relations") return jsonResponse(200, []);
      if (request.pathname === "/v1/rulebook/rules") {
        return problemResponse(503, { title: "Rules unavailable" });
      }
      return problemResponse(404);
    });
    const home = await getAdminHome(admin, { fetchImpl: fake.fetchImpl });
    expect(home.tiles.map((tile) => [tile.key, tile.value])).toEqual([
      ["entityGroups", "1"],
      ["relationCandidates", "0"],
      ["rules", null],
      ["prompts", null],
    ]);
    expect(home.tiles[0]?.detail).toBe("4 open mentions in these groups");
    expect(home.tiles[2]?.error).toMatchObject({ message: "Rules unavailable", status: 503 });
    expect(home.tiles[3]?.error?.message).toBe("The service could not be reached.");
    expect(home.services.up).toBe(9);
    expect(home.services.total).toBe(10);
    expect(home.services.down).toEqual([
      { service: "llm-gateway", baseUrl: "http://localhost:9208", reason: "unreachable" },
    ]);
  });
});
