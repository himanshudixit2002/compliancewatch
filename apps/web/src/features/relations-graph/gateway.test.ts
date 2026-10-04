// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import { resetEnvCache } from "@/server/env";
import { fakeFetch } from "@/test/fake-fetch";
import { EXAMPLE_ENTITY_ID } from "@/test/rulebook-fixture";
import { EXAMPLE_VERSION_ID, ruleVersionDto } from "@/test/rule-version-fixture";
import { RELATIONS_LIMIT, graphGateway } from "./gateway";

const RULEBOOK = "http://localhost:8003";

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("GraphGateway", () => {
  it("reads a version and the relations at a version or an entity, uncached", async () => {
    const fake = fakeFetch([
      { path: `/v1/rulebook/rule-versions/${EXAMPLE_VERSION_ID}`, body: ruleVersionDto() },
      { path: "/v1/rulebook/relations", body: [] },
    ]);
    const gateway = graphGateway({ fetchImpl: fake.fetchImpl });
    expect(await gateway.version(EXAMPLE_VERSION_ID)).toMatchObject({ ok: true });
    await gateway.relations({ from: EXAMPLE_VERSION_ID, publishedOnly: false });
    await gateway.relations({ to: EXAMPLE_VERSION_ID, publishedOnly: true });
    await gateway.relations({ toEntity: EXAMPLE_ENTITY_ID, publishedOnly: false });
    expect(fake.requests.map((request) => request.url)).toEqual([
      `${RULEBOOK}/v1/rulebook/rule-versions/${EXAMPLE_VERSION_ID}`,
      `${RULEBOOK}/v1/rulebook/relations?published_only=false&limit=${RELATIONS_LIMIT}&from_rule_version_id=${EXAMPLE_VERSION_ID}`,
      `${RULEBOOK}/v1/rulebook/relations?published_only=true&limit=${RELATIONS_LIMIT}&to_rule_version_id=${EXAMPLE_VERSION_ID}`,
      `${RULEBOOK}/v1/rulebook/relations?published_only=false&limit=${RELATIONS_LIMIT}&to_entity_id=${EXAMPLE_ENTITY_ID}`,
    ]);
    for (const request of fake.requests) {
      expect(request.cache).toBe("no-store");
      expect(request.headers[TENANT_HEADER]).toBeUndefined();
    }
  });
});
