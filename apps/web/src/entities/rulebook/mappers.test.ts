import { describe, expect, it } from "vitest";
import { documentDto } from "@/test/rulebook-fixture";
import { clauseFromDto, documentFromDto } from "./mappers";

describe("documentFromDto", () => {
  it("maps every field and puts the clauses in reading order", () => {
    const document = documentFromDto(documentDto());
    expect(document).toMatchObject({
      documentId: "00000000-0000-0000-0000-00000000d0c1",
      sourceId: "00000000-0000-4000-8000-000000000000",
      regulator: "Example regulator",
      docType: "circular",
      externalRef: "Example 1/2000",
      title: "Example document title",
      language: "en",
      mediaType: "application/pdf",
      parserVersion: "example@0",
      publishedAt: "2000-01-15",
    });
    expect(document.clauses.map((clause) => clause.clauseRef)).toEqual(["en.p1", "en.p2", "en.p3"]);
  });

  it("keeps a missing page and a missing publication date as null", () => {
    expect(
      clauseFromDto({
        clause_id: "c",
        clause_ref: "en.p9",
        ordinal: 9,
        page: null,
        text: "Example clause text",
      }).page,
    ).toBeNull();
    expect(documentFromDto(documentDto({ published_at: null })).publishedAt).toBeNull();
  });
});
