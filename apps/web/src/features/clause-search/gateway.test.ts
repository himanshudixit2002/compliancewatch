// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import { resetEnvCache } from "@/server/env";
import { fakeFetch } from "@/test/fake-fetch";
import { searchGateway } from "./gateway";

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("SearchGateway", () => {
  it("posts the words with the filters and no vector, without a tenant header", async () => {
    const fake = fakeFetch([{ method: "POST", path: "/v1/rulebook/search", body: [] }]);
    const hits = await searchGateway({ fetchImpl: fake.fetchImpl }).search({
      text: "Example words",
      docTypes: ["circular"],
      k: 20,
      asOf: "2000-06-30",
    });
    expect(hits).toEqual({ ok: true, value: [], requestId: expect.any(String) });
    const [request] = fake.requests;
    expect(request?.url).toBe("http://localhost:8003/v1/rulebook/search");
    expect(request?.body).toEqual({
      text: "Example words",
      k: 20,
      doc_types: ["circular"],
      as_of: "2000-06-30",
    });
    expect(request?.headers[TENANT_HEADER]).toBeUndefined();
  });
});
