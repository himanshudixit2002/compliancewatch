import { describe, expect, it } from "vitest";
import { searchHitFromDto } from "@/entities/rulebook/mappers";
import type { SearchHitDto } from "@/entities/rulebook/types";
import { EXAMPLE_CLAUSE_IDS, EXAMPLE_DOCUMENT_ID } from "@/test/rulebook-fixture";
import { EXAMPLE_VERSION_ID } from "@/test/rule-version-fixture";
import { hitView, markTerms, queryTerms, searchResults } from "./hits";

const HIT: SearchHitDto = {
  clause_id: EXAMPLE_CLAUSE_IDS.first,
  document_id: EXAMPLE_DOCUMENT_ID,
  clause_ref: "en.p1",
  text: "Example clauses furnish the Example return; furnishing is due.",
  regulator: "Example regulator",
  doc_type: "press_release",
  external_ref: "Example 1/2000",
  title: "Example document title",
  published_at: "2000-01-15",
  score: 0.032786885,
  lexical_rank: 1,
  vector_rank: null,
  cited_by: [EXAMPLE_VERSION_ID],
  out_of_force: true,
};

describe("queryTerms", () => {
  it("keeps the words worth marking, lower-cased, once each", () => {
    expect(queryTerms("Furnish the return, FURNISH it at 20 or 2000!")).toEqual([
      "furnish",
      "return",
      "2000",
    ]);
    expect(queryTerms("a of to")).toEqual([]);
  });
});

describe("markTerms", () => {
  it("marks the words that start with a term, whatever their case", () => {
    expect(markTerms(HIT.text, ["furnish", "example"])).toEqual([
      { text: "Example", mark: true },
      { text: " clauses ", mark: false },
      { text: "furnish", mark: true },
      { text: " the ", mark: false },
      { text: "Example", mark: true },
      { text: " return; ", mark: false },
      { text: "furnish", mark: true },
      { text: "ing is due.", mark: false },
    ]);
  });

  it("does not mark a term inside a word, and counts in code points", () => {
    expect(markTerms("Prefurnish 𝔸 furnish", ["furnish"])).toEqual([
      { text: "Prefurnish 𝔸 ", mark: false },
      { text: "furnish", mark: true },
    ]);
    expect(markTerms("Example (a.b)", ["a.b"])).toEqual([
      { text: "Example (", mark: false },
      { text: "a.b", mark: true },
      { text: ")", mark: false },
    ]);
  });
});

describe("hitView", () => {
  it("keeps the ranks as returned and links to the clause and the citing versions", () => {
    const view = hitView(searchHitFromDto(HIT), 0, ["furnish"]);
    expect(view).toMatchObject({
      rank: 1,
      clauseRef: "en.p1",
      docTypeLabel: "Press release",
      score: "0.0328",
      lexicalRank: 1,
      vectorRank: null,
      outOfForce: true,
      citedBy: [
        {
          ruleVersionId: EXAMPLE_VERSION_ID,
          href: `/admin/rulebook/versions/${EXAMPLE_VERSION_ID}`,
        },
      ],
      documentHref: `/admin/rulebook/documents/${EXAMPLE_DOCUMENT_ID}?clause_id=${EXAMPLE_CLAUSE_IDS.first}`,
    });
    const results = searchResults("furnish returns", [searchHitFromDto(HIT)]);
    expect(results.terms).toEqual(["furnish", "returns"]);
    expect(results.hits[0]?.segments.filter((segment) => segment.mark)).toHaveLength(2);
  });
});
