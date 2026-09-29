import { describe, expect, it } from "vitest";
import { documentFromDto } from "@/entities/rulebook/mappers";
import { EXAMPLE_CLAUSE_IDS, documentDto } from "@/test/rulebook-fixture";
import { clauseAnchorId, toDocumentView } from "./document-view";

const document = documentFromDto(documentDto());

describe("toDocumentView", () => {
  it("gives the header facts and the clauses in reading order with anchors and pages", () => {
    const view = toDocumentView(document, null);
    expect(view.title).toBe("Example document title");
    expect(view.externalRef).toBe("Example 1/2000");
    expect(view.header.map((item) => [item.key, item.value])).toEqual([
      ["regulator", "Example regulator"],
      ["docType", "Circular"],
      ["externalRef", "Example 1/2000"],
      ["publishedAt", "15 Jan 2000"],
      ["url", "https://example.com/example-document.pdf"],
      ["language", "en"],
      ["mediaType", "application/pdf"],
      ["parserVersion", "example@0"],
      ["documentId", "00000000-0000-0000-0000-00000000d0c1"],
      ["sha256", `${"0".repeat(60)}d0c1`],
      ["sourceId", "00000000-0000-4000-8000-000000000000"],
    ]);
    expect(view.header.find((item) => item.key === "url")?.href).toBe(
      "https://example.com/example-document.pdf",
    );
    expect(view.header.filter((item) => item.copy !== undefined).map((item) => item.key)).toEqual([
      "documentId",
      "sha256",
      "sourceId",
    ]);
    expect(view.clauses.map((clause) => [clause.anchorId, clause.page, clause.mark])).toEqual([
      ["clause-en.p1", 1, null],
      ["clause-en.p2", null, null],
      ["clause-en.p3", 2, null],
    ]);
    expect(view.highlight).toEqual({ kind: "none" });
    expect(view.markedAnchorId).toBeNull();
  });

  it("says when the document gives no publication date", () => {
    const view = toDocumentView(documentFromDto(documentDto({ published_at: null })), null);
    expect(view.header.find((item) => item.key === "publishedAt")?.value).toBe("Not recorded");
  });

  it("marks a span that fits its clause, in code points", () => {
    const view = toDocumentView(document, {
      clauseId: EXAMPLE_CLAUSE_IDS.third,
      span: { start: 8, end: 14 },
    });
    const clause = view.clauses[2];
    expect(clause?.mark).toBe("span");
    expect(clause?.parts).toEqual({
      before: "Example ",
      mark: "clause",
      after: " text on the second page.",
    });
    expect(view.highlight).toEqual({ kind: "span", clauseRef: "en.p3", start: 8, end: 14 });
    expect(view.markedAnchorId).toBe("clause-en.p3");
  });

  it("marks the whole clause when the link asks for it", () => {
    const view = toDocumentView(document, { clauseId: EXAMPLE_CLAUSE_IDS.second });
    expect(view.clauses[1]?.mark).toBe("clause");
    expect(view.highlight).toEqual({ kind: "clause", clauseRef: "en.p2" });
  });

  it("falls back to the whole clause when the span runs past its text, and says so", () => {
    const view = toDocumentView(document, {
      clauseId: EXAMPLE_CLAUSE_IDS.first,
      span: { start: 40, end: 400 },
    });
    expect(view.clauses[0]?.mark).toBe("clause");
    expect(view.clauses[0]?.parts).toBeNull();
    expect(view.highlight).toEqual({ kind: "fallback", clauseRef: "en.p1", start: 40, end: 400 });
    expect(view.markedAnchorId).toBe("clause-en.p1");
  });

  it("marks nothing for a clause the document does not hold, or a malformed link", () => {
    const missing = toDocumentView(document, { clauseId: "00000000-0000-5000-8000-00000000ffff" });
    expect(missing.highlight).toEqual({
      kind: "missing",
      clauseId: "00000000-0000-5000-8000-00000000ffff",
    });
    expect(missing.clauses.every((clause) => clause.mark === null)).toBe(true);
    expect(toDocumentView(document, "invalid").highlight).toEqual({ kind: "invalid" });
  });

  it("keeps anchors unique and safe", () => {
    expect(clauseAnchorId("en.p3")).toBe("clause-en.p3");
    expect(clauseAnchorId("hi p/1")).toBe("clause-hi-p-1");
    const twice = documentFromDto(
      documentDto({
        clauses: [
          { clause_id: "a", clause_ref: "en.p1", ordinal: 1, page: 1, text: "Example" },
          { clause_id: "b", clause_ref: "en.p1", ordinal: 2, page: 1, text: "Example" },
        ],
      }),
    );
    expect(toDocumentView(twice, null).clauses.map((clause) => clause.anchorId)).toEqual([
      "clause-en.p1",
      "clause-en.p1-2",
    ]);
  });
});
