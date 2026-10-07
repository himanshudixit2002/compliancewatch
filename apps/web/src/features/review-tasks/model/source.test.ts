import { describe, expect, it } from "vitest";
import { documentFromDto } from "@/entities/rulebook/mappers";
import { documentDetailFromDto } from "@/entities/pipeline/mappers";
import { citationFromDto, taskDocumentFromDto } from "@/entities/rule-version/mappers";
import type { DocumentDetail } from "@/entities/pipeline/types";
import type { RulebookDocument } from "@/entities/rulebook/types";
import { err, ok, webError, type Result } from "@/server/result";
import { EXAMPLE_CLAUSE_IDS, EXAMPLE_DOCUMENT_ID, documentDto } from "@/test/rulebook-fixture";
import { citationDto } from "@/test/rule-version-fixture";
import { taskDocumentDto } from "@/test/review-task-fixture";
import { documentDetailDto as pipelineDocumentDetailDto } from "@/test/pipeline-fixture";
import { sourceAnchorId, sourceFile, sourcePane } from "./source";

const DOCUMENT = documentFromDto(documentDto());

function pane(
  quotes: { clauseId: string; quote: string }[],
  stored: ReadonlyMap<string, Result<DocumentDetail>> = new Map(),
  documents: ReadonlyMap<string, Result<RulebookDocument>> = new Map([
    [EXAMPLE_DOCUMENT_ID, ok(DOCUMENT)],
  ]),
) {
  return sourcePane({
    documentIds: [EXAMPLE_DOCUMENT_ID],
    candidateDocumentId: null,
    facts: new Map([[EXAMPLE_DOCUMENT_ID, taskDocumentFromDto(taskDocumentDto())]]),
    documents,
    stored,
    quotes,
    citations: [citationFromDto(citationDto())],
  });
}

describe("sourcePane", () => {
  it("marks a quote its clause holds word for word, and leaves the other clauses plain", () => {
    const view = pane([{ clauseId: EXAMPLE_CLAUSE_IDS.first, quote: "clause text that opens" }]);
    const [document] = view.documents;
    expect(document).toMatchObject({
      documentId: EXAMPLE_DOCUMENT_ID,
      title: "Example document title",
      externalRef: "Example 1/2000",
      facts: "Example regulator, Circular, 15 Jan 2000",
      role: "cited",
      viewerHref: `/admin/rulebook/documents/${EXAMPLE_DOCUMENT_ID}`,
      file: { kind: "none" },
      clausesError: null,
    });
    const first = document?.clauses?.[0];
    expect(first).toMatchObject({
      clauseRef: "en.p1",
      anchorId: sourceAnchorId(EXAMPLE_DOCUMENT_ID, "en.p1"),
      wholeMarked: false,
      unmatched: [],
      quotes: 1,
      // "Example " (8 code points), the quote (22), " the document." (14).
      runs: [
        { start: 0, end: 8, mark: false },
        { start: 8, end: 30, mark: true },
        { start: 30, end: 44, mark: false },
      ],
    });
    expect(document?.clauses?.[1]).toMatchObject({ quotes: 0, wholeMarked: false });
    // Every clause shown has its text once, by id, for the pane and the forms alike.
    expect(view.clauseTexts[EXAMPLE_CLAUSE_IDS.first]).toBe(
      "Example clause text that opens the document.",
    );
    expect(Object.keys(view.clauseTexts)).toHaveLength(document?.clauses?.length ?? 0);
  });

  it("marks the whole clause and says so when a quote does not match it word for word", () => {
    const view = pane([
      { clauseId: EXAMPLE_CLAUSE_IDS.first, quote: "Example  clause text" },
      { clauseId: EXAMPLE_CLAUSE_IDS.first, quote: "Example  clause text" },
    ]);
    expect(view.documents[0]?.clauses?.[0]).toMatchObject({
      wholeMarked: true,
      unmatched: ["Example  clause text"],
      quotes: 1,
      runs: [{ start: 0, end: 44, mark: true }],
    });
  });

  it("links each citation to its clause in the pane, or in the viewer when its clauses are not read", () => {
    expect(pane([]).citations[0]).toEqual({
      citationId: citationDto().citation_id,
      clauseRef: "en.p1",
      quote: "Example clause text that opens",
      verified: true,
      score: "97%",
      verifiedAt: "1 May 2000, 12:00 pm IST",
      anchorHref: `#${sourceAnchorId(EXAMPLE_DOCUMENT_ID, "en.p1")}`,
      viewerHref: `/admin/rulebook/documents/${EXAMPLE_DOCUMENT_ID}?clause_id=${EXAMPLE_CLAUSE_IDS.first}`,
    });
    const failed = err(webError("server", "example", "Example failure"));
    const view = pane([], new Map(), new Map([[EXAMPLE_DOCUMENT_ID, failed]]));
    expect(view.documents[0]).toMatchObject({
      clauses: null,
      clausesError: { message: "Example failure" },
      title: "Example document title",
    });
    expect(view.citations[0]?.anchorHref).toBeNull();
  });
});

describe("sourceFile", () => {
  it("links the stored file through the handler with its type and size", () => {
    const stored = ok(documentDetailFromDto(pipelineDocumentDetailDto()));
    expect(sourceFile(EXAMPLE_DOCUMENT_ID, stored)).toEqual({
      kind: "stored",
      href: `/api-bff/pipeline/documents/${EXAMPLE_DOCUMENT_ID}/raw`,
      type: "PDF",
      size: "20.5 KB",
    });
  });

  it("says the pipeline holds no file for a 404, and passes any other failure on", () => {
    expect(
      sourceFile(EXAMPLE_DOCUMENT_ID, err(webError("not_found", "example", "Example"))),
    ).toEqual({
      kind: "none",
    });
    expect(sourceFile(EXAMPLE_DOCUMENT_ID, undefined)).toEqual({ kind: "none" });
    expect(
      sourceFile(EXAMPLE_DOCUMENT_ID, err(webError("unavailable", "example", "Example away"))),
    ).toMatchObject({ kind: "error", error: { message: "Example away" } });
  });
});
