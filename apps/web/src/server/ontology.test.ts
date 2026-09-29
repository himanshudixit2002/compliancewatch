// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeFetch, refusingFetch } from "@/test/fake-fetch";
import { ONTOLOGY_DTO } from "@/test/ontology-fixture";
import { CACHED_REQUEST_ID_PREFIX, REQUEST_ID_HEADER, TENANT_HEADER } from "./api/client";
import { resetEnvCache } from "./env";
import { ONTOLOGY_REVALIDATE_SECONDS, getOntology, readOntology } from "./ontology";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  resetEnvCache();
});

describe("readOntology", () => {
  it("reads GET /v1/ontology without a tenant, cached under the ontology tag for an hour", async () => {
    const fake = fakeFetch([{ method: "GET", path: "/v1/ontology", body: ONTOLOGY_DTO }]);
    const result = await readOntology({ fetchImpl: fake.fetchImpl });
    expect(result.ok && result.requestId).toBe(`${CACHED_REQUEST_ID_PREFIX}profile:ontology`);
    const [request] = fake.requests;
    expect(request?.url).toBe("http://localhost:8002/v1/ontology");
    expect(request?.method).toBe("GET");
    expect(request?.headers[TENANT_HEADER]).toBeUndefined();
    expect(request?.headers[REQUEST_ID_HEADER]).toBe(`${CACHED_REQUEST_ID_PREFIX}profile:ontology`);
    expect(request?.next).toEqual({ revalidate: 3600, tags: ["profile:ontology"] });
    expect(ONTOLOGY_REVALIDATE_SECONDS).toBe(3600);
  });

  it("maps the body to the domain ontology", async () => {
    const fake = fakeFetch([{ path: "/v1/ontology", body: ONTOLOGY_DTO }]);
    const result = await readOntology({ fetchImpl: fake.fetchImpl });
    if (!result.ok) throw new Error(result.error.message);
    expect(result.value.version).toBe("0.0.1");
    expect(result.value.attributes[0]).toMatchObject({
      key: "example_kind",
      type: "enum",
      level: "registration",
      source: "gstin_lookup",
      help: "Example help line.",
    });
  });

  it("reports the service's problem with the request id", async () => {
    const fake = fakeFetch([
      {
        path: "/v1/ontology",
        status: 500,
        problem: { type: "urn:compliancewatch:problem:internal", title: "Internal error" },
      },
    ]);
    const result = await readOntology({ fetchImpl: fake.fetchImpl });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toMatchObject({ kind: "server", status: 500, message: "Internal error" });
    expect(result.error.requestId).toBe(`${CACHED_REQUEST_ID_PREFIX}profile:ontology`);
  });

  it("refuses a success without a body rather than an empty ontology", async () => {
    const fake = fakeFetch([
      { path: "/v1/ontology", status: 200, headers: { "content-length": "0" } },
    ]);
    const result = await readOntology({ fetchImpl: fake.fetchImpl });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.kind).toBe("server");
      expect(result.error.problem?.type).toBe("urn:compliancewatch:problem:web-ontology-empty");
    }
  });

  it("reports a refused connection as a network failure", async () => {
    const result = await readOntology({ fetchImpl: refusingFetch().fetchImpl });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("network");
  });

  it("reads the profile service the environment names", async () => {
    vi.stubEnv("CW_WEB_PROFILE_URL", "http://localhost:9202/");
    resetEnvCache();
    const fake = fakeFetch([{ path: "/v1/ontology", body: ONTOLOGY_DTO }]);
    await readOntology({ fetchImpl: fake.fetchImpl });
    expect(fake.requests[0]?.url).toBe("http://localhost:9202/v1/ontology");
  });
});

describe("getOntology", () => {
  it("reads through the process fetch", async () => {
    const fake = fakeFetch([{ path: "/v1/ontology", body: ONTOLOGY_DTO }]);
    vi.stubGlobal("fetch", fake.fetchImpl);
    const result = await getOntology();
    expect(result.ok).toBe(true);
    expect(fake.requests[0]?.pathname).toBe("/v1/ontology");
  });
});
