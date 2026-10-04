// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import { resetEnvCache } from "@/server/env";
import { fakeFetch } from "@/test/fake-fetch";
import {
  EXAMPLE_ENTITY_ID,
  entityDto,
  mentionedClauseDto,
  relationDto,
} from "@/test/rulebook-fixture";
import { EXAMPLE_VERSION_ID, ruleVersionDto } from "@/test/rule-version-fixture";
import { RELATIONS_LIMIT, entitiesGateway } from "./gateway";

const RULEBOOK = "http://localhost:8003";

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("EntitiesGateway", () => {
  it("resolves a name and reads an entity, its clauses, its relations and a version, uncached", async () => {
    const fake = fakeFetch([
      {
        path: "/v1/rulebook/entities/resolve",
        body: {
          status: "resolved",
          entity_type: "form",
          name: "Example Form",
          normalised: "example form",
          entity: entityDto(),
          candidates: [],
        },
      },
      { path: `/v1/rulebook/entities/${EXAMPLE_ENTITY_ID}`, body: entityDto() },
      { path: `/v1/rulebook/entities/${EXAMPLE_ENTITY_ID}/clauses`, body: [mentionedClauseDto()] },
      { path: "/v1/rulebook/relations", body: [relationDto()] },
      { path: `/v1/rulebook/rule-versions/${EXAMPLE_VERSION_ID}`, body: ruleVersionDto() },
    ]);
    const gateway = entitiesGateway({ fetchImpl: fake.fetchImpl });
    expect(await gateway.resolve("form", "Example Form")).toMatchObject({
      ok: true,
      value: { status: "resolved", entity: { canonicalName: "example form" } },
    });
    expect(await gateway.entity(EXAMPLE_ENTITY_ID)).toMatchObject({ ok: true });
    expect(await gateway.clauses(EXAMPLE_ENTITY_ID, { limit: 50 })).toMatchObject({
      ok: true,
      value: [{ mentions: [{ start: 21, end: 33 }, {}] }],
    });
    await gateway.clauses(EXAMPLE_ENTITY_ID, { limit: 50, asOf: "2000-06-30" });
    expect(await gateway.relationsTo(EXAMPLE_ENTITY_ID)).toMatchObject({
      ok: true,
      value: [{ toEntityId: EXAMPLE_ENTITY_ID }],
    });
    expect(await gateway.version(EXAMPLE_VERSION_ID)).toMatchObject({ ok: true });
    expect(fake.requests.map((request) => request.url)).toEqual([
      `${RULEBOOK}/v1/rulebook/entities/resolve?type=form&name=Example%20Form`,
      `${RULEBOOK}/v1/rulebook/entities/${EXAMPLE_ENTITY_ID}`,
      `${RULEBOOK}/v1/rulebook/entities/${EXAMPLE_ENTITY_ID}/clauses?limit=50`,
      `${RULEBOOK}/v1/rulebook/entities/${EXAMPLE_ENTITY_ID}/clauses?limit=50&as_of=2000-06-30`,
      `${RULEBOOK}/v1/rulebook/relations?to_entity_id=${EXAMPLE_ENTITY_ID}&published_only=false&limit=${RELATIONS_LIMIT}`,
      `${RULEBOOK}/v1/rulebook/rule-versions/${EXAMPLE_VERSION_ID}`,
    ]);
    for (const request of fake.requests) {
      expect(request.cache).toBe("no-store");
      expect(request.headers[TENANT_HEADER]).toBeUndefined();
    }
  });
});
