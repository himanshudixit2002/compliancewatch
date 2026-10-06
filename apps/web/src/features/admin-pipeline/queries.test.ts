// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { fakeFetch, jsonResponse, problemResponse } from "@/test/fake-fetch";
import {
  ACTOR_ID,
  DOCUMENT_ID,
  documentDetailDto,
  outboxEventDto,
  pipelineDocumentDto,
  runDto,
  sourceDto,
  taskDto,
} from "@/test/pipeline-fixture";
import { readPipelineQuery } from "./model/operations";
import { controlAccess, getDocumentPage, getPipelinePage, getTasksPage } from "./queries";

const ADMIN: ClientPrincipal = {
  userId: ACTOR_ID,
  tenantId: "00000000-0000-4000-8000-0000000000ee",
  tenantKind: "internal",
  roles: ["admin"],
};
const ANALYST: ClientPrincipal = { ...ADMIN, roles: ["analyst"] };

function stack() {
  return fakeFetch((request) => {
    switch (request.pathname) {
      case "/v1/pipeline/runs":
        return jsonResponse(200, { items: [runDto()], next_cursor: "n" });
      case "/v1/pipeline/documents":
        return jsonResponse(200, { items: [pipelineDocumentDto()], next_cursor: null });
      case "/v1/pipeline/outbox/dead":
        return jsonResponse(200, { items: [outboxEventDto()], next_cursor: null });
      case "/v1/pipeline/sources":
        return jsonResponse(200, { items: [sourceDto()] });
      case "/v1/pipeline/tasks":
        return jsonResponse(200, { items: [taskDto()], next_cursor: null });
      case `/v1/pipeline/documents/${DOCUMENT_ID}`:
        return jsonResponse(200, documentDetailDto());
      default:
        return problemResponse(404);
    }
  });
}

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("getPipelinePage", () => {
  it("reads the view the query names with the sources for its filter", async () => {
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", "example-write-token");
    const fake = stack();
    const runs = await getPipelinePage(ADMIN, readPipelineQuery({}), { fetchImpl: fake.fetchImpl });
    expect(runs.list?.view).toBe("runs");
    expect(runs.list?.list.nextHref).toBe("/admin/pipeline?cursor=n");
    expect(runs.sourceKeys).toEqual(["example_notices"]);
    expect(runs.access).toEqual({ allowed: true });
    const documents = await getPipelinePage(ADMIN, readPipelineQuery({ view: "documents" }), {
      fetchImpl: fake.fetchImpl,
    });
    expect(documents.list?.view === "documents" && documents.list.list.rows[0]?.documentId).toBe(
      DOCUMENT_ID,
    );
    const outbox = await getPipelinePage(ANALYST, readPipelineQuery({ view: "outbox" }), {
      fetchImpl: fake.fetchImpl,
    });
    expect(outbox.list?.view).toBe("outbox");
    expect(outbox.sourceKeys).toBeNull();
    expect(outbox.access).toEqual({
      allowed: false,
      title: "Only an admin retries, requeues or resolves",
    });
  });

  it("reads no list for a refused field, and keeps a failed read's error", async () => {
    const fake = stack();
    const refused = await getPipelinePage(
      ADMIN,
      readPipelineQuery({ view: "outbox", topic: "Bad" }),
      {
        fetchImpl: fake.fetchImpl,
      },
    );
    expect(refused.list).toBeNull();
    expect(refused.listError).toBeNull();
    expect(fake.requests).toHaveLength(0);
    const failing = fakeFetch(() => problemResponse(500));
    const failed = await getPipelinePage(ADMIN, readPipelineQuery({}), {
      fetchImpl: failing.fetchImpl,
    });
    expect(failed.listError?.status).toBe(500);
    expect(failed.sourceKeys).toBeNull();
    for (const view of ["documents", "outbox"]) {
      const page = await getPipelinePage(ADMIN, readPipelineQuery({ view }), {
        fetchImpl: failing.fetchImpl,
      });
      expect(page.listError?.status, view).toBe(500);
    }
  });

  it("names the variable when the token is missing", () => {
    vi.stubEnv("CW_WEB_RULEBOOK_WRITE_TOKEN", "");
    resetEnvCache();
    const access = controlAccess(ADMIN);
    expect(!access.allowed && access.detail).toContain("CW_WEB_RULEBOOK_WRITE_TOKEN");
  });
});

describe("getDocumentPage and getTasksPage", () => {
  it("reads a document with a fresh key for its retry, and null for an unknown one", async () => {
    const fake = stack();
    const page = await getDocumentPage(ADMIN, DOCUMENT_ID, { fetchImpl: fake.fetchImpl });
    expect(page.ok && page.value?.view.documentId).toBe(DOCUMENT_ID);
    const again = await getDocumentPage(ADMIN, DOCUMENT_ID, { fetchImpl: fake.fetchImpl });
    expect(page.ok && again.ok && page.value?.retryKey !== again.value?.retryKey).toBe(true);
    expect(
      await getDocumentPage(ADMIN, "00000000-0000-4000-8000-000000000000", {
        fetchImpl: fake.fetchImpl,
      }),
    ).toEqual({
      ok: true,
      value: null,
    });
    const down = fakeFetch(() => problemResponse(503));
    expect((await getDocumentPage(ADMIN, DOCUMENT_ID, { fetchImpl: down.fetchImpl })).ok).toBe(
      false,
    );
  });

  it("reads a page of tasks with the session's access", async () => {
    const fake = stack();
    const page = await getTasksPage(
      ANALYST,
      { status: "open", kind: null, cursor: null },
      { fetchImpl: fake.fetchImpl },
    );
    expect(page.ok && page.value.view.cards).toHaveLength(1);
    expect(page.ok && page.value.access.allowed).toBe(false);
    const down = fakeFetch(() => problemResponse(503));
    expect(
      (
        await getTasksPage(
          ADMIN,
          { status: null, kind: null, cursor: null },
          { fetchImpl: down.fetchImpl },
        )
      ).ok,
    ).toBe(false);
  });
});
