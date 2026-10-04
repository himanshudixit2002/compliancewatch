// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import { resetEnvCache } from "@/server/env";
import { fakeFetch } from "@/test/fake-fetch";
import { ONTOLOGY_DTO } from "@/test/ontology-fixture";
import { getOntologyBrowser } from "./queries";

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("getOntologyBrowser", () => {
  it("reads the ontology without a tenant, cached under its tag, and groups it by level", async () => {
    const fake = fakeFetch([{ method: "GET", path: "/v1/ontology", body: ONTOLOGY_DTO }]);
    const view = await getOntologyBrowser({ fetchImpl: fake.fetchImpl });
    expect(view.ok && view.value.sections.map((section) => section.level)).toEqual([
      "entity",
      "registration",
      "location",
    ]);
    expect(fake.requests[0]?.url).toBe("http://localhost:8002/v1/ontology");
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBeUndefined();
    expect(fake.requests[0]?.next).toEqual({ revalidate: 3600, tags: ["profile:ontology"] });
  });

  it("passes the service's problem on", async () => {
    const fake = fakeFetch([
      {
        method: "GET",
        path: "/v1/ontology",
        status: 503,
        problem: { title: "Example outage", detail: "Example detail" },
      },
    ]);
    const view = await getOntologyBrowser({ fetchImpl: fake.fetchImpl });
    expect(!view.ok && view.error.kind).toBe("unavailable");
    expect(!view.ok && view.error.message).toBe("Example outage");
  });
});
