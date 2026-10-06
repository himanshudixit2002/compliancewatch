// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetEnvCache } from "@/server/env";
import { fakeFetch } from "@/test/fake-fetch";
import { SOURCE_KEY, documentDto, runDto, sourceDto } from "@/test/pipeline-fixture";
import { sourcesGateway } from "./gateway";

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("SourcesGateway", () => {
  it("reads the sources, runs and documents fresh, with no tenant header or token", async () => {
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", "example-write-token");
    const fake = fakeFetch([
      { method: "GET", path: "/v1/pipeline/sources", body: { items: [sourceDto()] } },
      { method: "GET", path: "/v1/pipeline/runs", body: { items: [runDto()], next_cursor: "n" } },
      {
        method: "GET",
        path: `/v1/pipeline/sources/${SOURCE_KEY}/documents`,
        body: { items: [documentDto()], next_cursor: null },
      },
    ]);
    const gateway = sourcesGateway({ fetchImpl: fake.fetchImpl });
    const sources = await gateway.sources();
    expect(sources.ok && sources.value[0]?.key).toBe(SOURCE_KEY);
    const runs = await gateway.runs({
      sourceKey: SOURCE_KEY,
      status: "failed",
      trigger: "backfill",
      limit: 10,
      cursor: "c1",
    });
    expect(runs.ok && runs.value.nextCursor).toBe("n");
    await gateway.runs({ sourceKey: null, status: null, trigger: null, limit: 1, cursor: null });
    const documents = await gateway.documents(SOURCE_KEY, "c2", 25);
    expect(documents.ok && documents.value.items[0]?.title).toBe("Example notice 1");
    await gateway.documents(SOURCE_KEY, null, 25);
    expect(
      fake.requests.map((request) => request.url.replace("http://localhost:8010", "")),
    ).toEqual([
      "/v1/pipeline/sources",
      "/v1/pipeline/runs?limit=10&source_key=example_notices&status=failed&trigger=backfill&cursor=c1",
      "/v1/pipeline/runs?limit=1",
      `/v1/pipeline/sources/${SOURCE_KEY}/documents?limit=25&cursor=c2`,
      `/v1/pipeline/sources/${SOURCE_KEY}/documents?limit=25`,
    ]);
    for (const request of fake.requests) {
      expect(request.cache).toBe("no-store");
      expect(request.headers["x-tenant-id"]).toBeUndefined();
      expect(request.headers["x-cw-write-token"]).toBeUndefined();
    }
  });
});
