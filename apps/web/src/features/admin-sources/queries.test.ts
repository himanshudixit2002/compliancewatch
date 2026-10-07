// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { fakeFetch, jsonResponse, problemResponse } from "@/test/fake-fetch";
import { ACTOR_ID, SOURCE_KEY, documentDto, runDto, sourceDto } from "@/test/pipeline-fixture";
import { crawlFlag, getSourcePage, getSourcesPage, sourceWriteAccess } from "./queries";

const ADMIN: ClientPrincipal = {
  userId: ACTOR_ID,
  tenantId: "00000000-0000-4000-8000-0000000000ee",
  tenantKind: "internal",
  roles: ["admin"],
};
const ANALYST: ClientPrincipal = { ...ADMIN, roles: ["analyst"] };

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("getSourcesPage", () => {
  it("lists the sources with the crawl flag and the schedule's latest crawl", async () => {
    const fake = fakeFetch([
      { method: "GET", path: "/v1/pipeline/sources", body: { items: [sourceDto()] } },
      { method: "GET", path: "/v1/pipeline/runs", body: { items: [runDto()], next_cursor: null } },
    ]);
    const page = await getSourcesPage({ fetchImpl: fake.fetchImpl });
    expect(page.ok).toBe(true);
    if (!page.ok) return;
    expect(page.value.rows).toHaveLength(1);
    expect(page.value.crawl.flag).toEqual({
      name: "pipeline.crawl",
      variable: "CW_PIPELINE_CRAWL_ENABLED",
      defaultOn: false,
      owner: "regulatory-intelligence",
    });
    expect(page.value.crawl.latestScheduled).toMatchObject({
      kind: "run",
      sourceKey: SOURCE_KEY,
      summary: { statusLabel: "Completed" },
    });
    expect(fake.requests[1]?.url).toContain("trigger=schedule");
    expect(crawlFlag().defaultOn).toBe(false);
  });

  it("says when the schedule never crawled or its runs could not be read, and fails on the list", async () => {
    const none = fakeFetch([
      { method: "GET", path: "/v1/pipeline/sources", body: { items: [] } },
      { method: "GET", path: "/v1/pipeline/runs", body: { items: [], next_cursor: null } },
    ]);
    const empty = await getSourcesPage({ fetchImpl: none.fetchImpl });
    expect(empty.ok && empty.value.crawl.latestScheduled).toEqual({ kind: "none" });
    const broken = fakeFetch([
      { method: "GET", path: "/v1/pipeline/sources", body: { items: [] } },
      {
        method: "GET",
        path: "/v1/pipeline/runs",
        status: 500,
        problem: { title: "Example failure" },
      },
    ]);
    const unknown = await getSourcesPage({ fetchImpl: broken.fetchImpl });
    expect(unknown.ok && unknown.value.crawl.latestScheduled).toMatchObject({
      kind: "error",
      message: "Example failure",
    });
    const failed = fakeFetch([
      { method: "GET", path: "/v1/pipeline/sources", status: 503, problem: {} },
    ]);
    expect((await getSourcesPage({ fetchImpl: failed.fetchImpl })).ok).toBe(false);
  });
});

describe("getSourcePage", () => {
  function routes(overrides: Partial<Record<"documents" | "runs", () => Response>> = {}) {
    return fakeFetch((request) => {
      if (request.pathname === "/v1/pipeline/sources") {
        return jsonResponse(200, { items: [sourceDto()] });
      }
      if (request.pathname.endsWith("/documents")) {
        return (
          overrides.documents?.() ?? jsonResponse(200, { items: [documentDto()], next_cursor: "n" })
        );
      }
      return overrides.runs?.() ?? jsonResponse(200, { items: [runDto()], next_cursor: null });
    });
  }

  it("reads the source, a page of its documents and its latest runs", async () => {
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", "example-write-token");
    const fake = routes();
    const page = await getSourcePage(ADMIN, SOURCE_KEY, "c1", { fetchImpl: fake.fetchImpl });
    expect(page.ok).toBe(true);
    if (!page.ok || page.value === null) return;
    expect(page.value.facts.key).toBe(SOURCE_KEY);
    expect(page.value.documents).toMatchObject({
      nextHref: `/admin/sources/${SOURCE_KEY}?cursor=n`,
      firstHref: `/admin/sources/${SOURCE_KEY}`,
    });
    expect(page.value.runs).toHaveLength(1);
    expect(page.value.everyRunHref).toBe(`/admin/pipeline?view=runs&source=${SOURCE_KEY}`);
    expect(page.value.access).toEqual({ allowed: true });
    expect(page.value.upload).toEqual({
      href: `/api-bff/pipeline/sources/${SOURCE_KEY}/uploads`,
      maxBytes: 25_000_000,
    });
    expect(fake.requests.map((request) => request.url)).toContain(
      `http://localhost:8010/v1/pipeline/runs?limit=10&source_key=${SOURCE_KEY}`,
    );
  });

  it("keeps the page when its documents or runs fail, and answers null for an unknown key", async () => {
    const fake = routes({
      documents: () => problemResponse(422),
      runs: () => problemResponse(500),
    });
    const page = await getSourcePage(ANALYST, SOURCE_KEY, null, { fetchImpl: fake.fetchImpl });
    expect(page.ok && page.value?.documents).toBeNull();
    expect(page.ok && page.value?.documentsError?.status).toBe(422);
    expect(page.ok && page.value?.runsError?.status).toBe(500);
    expect(page.ok && page.value?.access).toEqual({
      allowed: false,
      title: "Only an admin changes a source",
    });
    const unknown = await getSourcePage(ANALYST, "example_unknown", null, {
      fetchImpl: fake.fetchImpl,
    });
    expect(unknown).toEqual({ ok: true, value: null });
    const down = fakeFetch(() => problemResponse(503));
    expect((await getSourcePage(ANALYST, SOURCE_KEY, null, { fetchImpl: down.fetchImpl })).ok).toBe(
      false,
    );
  });

  it("says an admin may not write while the token is missing, naming the variable", () => {
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", "");
    resetEnvCache();
    const access = sourceWriteAccess(ADMIN);
    expect(access.allowed).toBe(false);
    expect(!access.allowed && access.detail).toContain("CW_WEB_RULEBOOK_WRITE_TOKEN");
  });
});
