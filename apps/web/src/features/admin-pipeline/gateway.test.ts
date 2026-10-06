// @vitest-environment node
import { describe, expect, it } from "vitest";
import { fakeFetch } from "@/test/fake-fetch";
import {
  DOCUMENT_ID,
  documentDetailDto,
  outboxEventDto,
  pipelineDocumentDto,
  runDto,
  sourceDto,
  taskDto,
} from "@/test/pipeline-fixture";
import { pipelineGateway } from "./gateway";

describe("PipelineGateway", () => {
  it("reads every list with its filters and cursor, fresh and with no tenant header", async () => {
    const fake = fakeFetch([
      { method: "GET", path: "/v1/pipeline/runs", body: { items: [runDto()], next_cursor: null } },
      {
        method: "GET",
        path: "/v1/pipeline/documents",
        body: { items: [pipelineDocumentDto()], next_cursor: "n" },
      },
      { method: "GET", path: `/v1/pipeline/documents/${DOCUMENT_ID}`, body: documentDetailDto() },
      {
        method: "GET",
        path: "/v1/pipeline/outbox/dead",
        body: { items: [outboxEventDto()], next_cursor: null },
      },
      {
        method: "GET",
        path: "/v1/pipeline/tasks",
        body: { items: [taskDto()], next_cursor: null },
      },
      { method: "GET", path: "/v1/pipeline/sources", body: { items: [sourceDto()] } },
    ]);
    const gateway = pipelineGateway({ fetchImpl: fake.fetchImpl });
    expect(
      (
        await gateway.runs({
          sourceKey: "example_notices",
          status: "running",
          trigger: "schedule",
          limit: 25,
          cursor: "c",
        })
      ).ok,
    ).toBe(true);
    await gateway.runs({ sourceKey: null, status: null, trigger: null, limit: 25, cursor: null });
    const documents = await gateway.documents({
      status: "triage",
      sourceKey: "example_notices",
      docType: "circular",
      publishedFrom: "2000-01-01",
      publishedTo: "2000-12-31",
      limit: 25,
      cursor: "c",
    });
    expect(documents.ok && documents.value.nextCursor).toBe("n");
    await gateway.documents({
      status: null,
      sourceKey: null,
      docType: null,
      publishedFrom: null,
      publishedTo: null,
      limit: 25,
      cursor: null,
    });
    const document = await gateway.document(DOCUMENT_ID);
    expect(document.ok && document.value.retries).toHaveLength(1);
    expect(
      (await gateway.deadEvents({ topic: "document.parsed", limit: 25, cursor: "c" })).ok,
    ).toBe(true);
    await gateway.deadEvents({ topic: null, limit: 25, cursor: null });
    expect(
      (await gateway.tasks({ status: "open", kind: "triage", limit: 25, cursor: "c" })).ok,
    ).toBe(true);
    await gateway.tasks({ status: null, kind: null, limit: 25, cursor: null });
    const keys = await gateway.sourceKeys();
    expect(keys.ok && keys.value).toEqual(["example_notices"]);
    expect(
      fake.requests.map((request) => request.url.replace("http://localhost:8010", "")),
    ).toEqual([
      "/v1/pipeline/runs?limit=25&source_key=example_notices&status=running&trigger=schedule&cursor=c",
      "/v1/pipeline/runs?limit=25",
      "/v1/pipeline/documents?limit=25&status=triage&source_key=example_notices&doc_type=circular&published_from=2000-01-01&published_to=2000-12-31&cursor=c",
      "/v1/pipeline/documents?limit=25",
      `/v1/pipeline/documents/${DOCUMENT_ID}`,
      "/v1/pipeline/outbox/dead?limit=25&topic=document.parsed&cursor=c",
      "/v1/pipeline/outbox/dead?limit=25",
      "/v1/pipeline/tasks?limit=25&status=open&kind=triage&cursor=c",
      "/v1/pipeline/tasks?limit=25",
      "/v1/pipeline/sources",
    ]);
    for (const request of fake.requests) {
      expect(request.cache).toBe("no-store");
      expect(request.headers["x-tenant-id"]).toBeUndefined();
    }
  });
});
