// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { TENANT_HEADER, WRITE_TOKEN_HEADER } from "@/server/api/client";
import { resetEnvCache } from "@/server/env";
import { EXAMPLE_DOCUMENT_ID, documentDto } from "@/test/rulebook-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import { documentsGateway } from "./gateway";
import { getDocumentView } from "./queries";

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("DocumentsGateway", () => {
  it("reads one document under its own cache tag, with no tenant header and no token", async () => {
    const fake = fakeFetch([
      {
        method: "GET",
        path: `/v1/rulebook/documents/${EXAMPLE_DOCUMENT_ID}`,
        body: documentDto(),
      },
    ]);
    const document = await documentsGateway({ fetchImpl: fake.fetchImpl }).document(
      EXAMPLE_DOCUMENT_ID,
    );
    expect(document.ok && document.value.clauses.map((clause) => clause.ordinal)).toEqual([
      1, 2, 3,
    ]);
    const request = fake.requests[0];
    expect(request?.url).toBe(`http://localhost:8003/v1/rulebook/documents/${EXAMPLE_DOCUMENT_ID}`);
    expect(request?.next).toEqual({
      revalidate: 300,
      tags: [`rulebook:document:${EXAMPLE_DOCUMENT_ID}`],
    });
    expect(request?.headers[TENANT_HEADER]).toBeUndefined();
    expect(request?.headers[WRITE_TOKEN_HEADER]).toBeUndefined();
  });

  it("passes the rulebook's not-found problem on", async () => {
    const fake = fakeFetch([
      {
        path: /\/v1\/rulebook\/documents\//,
        status: 404,
        problem: {
          type: "urn:compliancewatch:problem:rulebook-document-not-found",
          title: "Document not found",
        },
      },
    ]);
    const document = await documentsGateway({ fetchImpl: fake.fetchImpl }).document(
      EXAMPLE_DOCUMENT_ID,
    );
    expect(document).toMatchObject({ ok: false, error: { kind: "not_found" } });
  });
});

describe("getDocumentView", () => {
  it("maps the document into the viewer's model with what the link asked to mark", async () => {
    const fake = fakeFetch([{ path: /\/v1\/rulebook\/documents\//, body: documentDto() }]);
    const view = await getDocumentView(
      EXAMPLE_DOCUMENT_ID,
      { clauseId: "00000000-0000-5000-8000-0000000000c1", span: { start: 0, end: 7 } },
      { fetchImpl: fake.fetchImpl },
    );
    expect(view.ok && view.value.highlight).toEqual({
      kind: "span",
      clauseRef: "en.p1",
      start: 0,
      end: 7,
    });
  });
});
