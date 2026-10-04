import { describe, expect, it } from "vitest";
import { citationReportFromDto } from "@/entities/rule-version/mappers";
import { EXAMPLE_CLAUSE_IDS, EXAMPLE_DOCUMENT_ID } from "@/test/rulebook-fixture";
import { citationDto } from "@/test/rule-version-fixture";
import {
  citationsResult,
  failuresByRow,
  parseCitationsForm,
  quoteFailures,
  unknownClauses,
} from "./citations-form";

function form(rows: readonly [string, string][]): FormData {
  const data = new FormData();
  rows.forEach(([clause, quote], index) => {
    data.append(`citations.${index}.clause_id`, clause);
    data.append(`citations.${index}.quote`, quote);
  });
  return data;
}

describe("parseCitationsForm", () => {
  it("reads the rows in order, trimmed, with the clause id lower-cased", () => {
    expect(
      parseCitationsForm(
        form([
          [` ${EXAMPLE_CLAUSE_IDS.first.toUpperCase()} `, " Example quote "],
          ["", ""],
          [EXAMPLE_CLAUSE_IDS.second, "Example other quote"],
        ]),
      ),
    ).toEqual({
      ok: true,
      citations: [
        { clauseId: EXAMPLE_CLAUSE_IDS.first, quote: "Example quote" },
        { clauseId: EXAMPLE_CLAUSE_IDS.second, quote: "Example other quote" },
      ],
    });
  });

  it("refuses a row on the part it lacks or gets wrong", () => {
    expect(
      parseCitationsForm(
        form([
          ["", "Example quote"],
          ["not-a-clause", "x".repeat(401)],
          [EXAMPLE_CLAUSE_IDS.first, ""],
        ]),
      ),
    ).toEqual({
      ok: false,
      formErrors: [],
      fieldErrors: {
        "citations.0.clause_id": ["Enter the clause's id."],
        "citations.1.clause_id": ["This is not a clause id (a UUID)."],
        "citations.1.quote": ["A quote has at most 400 characters."],
        "citations.2.quote": ["Enter the words of the clause the rule rests on."],
      },
    });
  });

  it("asks for at least one citation", () => {
    expect(parseCitationsForm(form([["", ""]]))).toEqual({
      ok: false,
      fieldErrors: {},
      formErrors: ["Add at least one citation: a clause id and a quote."],
    });
    expect(parseCitationsForm(new FormData())).toMatchObject({ ok: false });
  });
});

describe("the rulebook's refusals", () => {
  const prefix = `en.p1 of ${EXAMPLE_DOCUMENT_ID}`;

  it("lists each quote it could not find, from its detail", () => {
    expect(
      quoteFailures(
        `2 quotes are not in their clause: ${prefix}: score 0.40; en.p2 of x: score 0.10, missing 2000`,
      ),
    ).toEqual([`${prefix}: score 0.40`, "en.p2 of x: score 0.10, missing 2000"]);
    expect(quoteFailures("Example detail without a list")).toEqual([]);
    expect(quoteFailures(undefined)).toEqual([]);
  });

  it("reads the clause ids it does not hold", () => {
    expect(
      unknownClauses(`2 clauses are not stored: ${EXAMPLE_CLAUSE_IDS.first}, not-an-id`),
    ).toEqual([EXAMPLE_CLAUSE_IDS.first]);
    expect(unknownClauses("Example detail")).toEqual([]);
    expect(unknownClauses(undefined)).toEqual([]);
  });

  it("puts a failure on its row only when it cannot belong to another", () => {
    const rows = [
      { clauseRef: "en.p1", documentId: EXAMPLE_DOCUMENT_ID },
      { clauseRef: "en.p2", documentId: EXAMPLE_DOCUMENT_ID },
      { clauseRef: "en.p2", documentId: EXAMPLE_DOCUMENT_ID },
      { clauseRef: "", documentId: "" },
    ];
    expect(
      failuresByRow([`${prefix}: score 0.40`, `en.p2 of ${EXAMPLE_DOCUMENT_ID}: score 0.30`], rows),
    ).toEqual({ 0: "score 0.40" });
    expect(
      failuresByRow(
        [
          `en.p2 of ${EXAMPLE_DOCUMENT_ID}: score 0.30`,
          `en.p2 of ${EXAMPLE_DOCUMENT_ID}: score 0.20`,
        ],
        rows,
      ),
    ).toEqual({ 1: "score 0.30", 2: "score 0.20" });
  });
});

describe("citationsResult", () => {
  it("gives each submitted quote's verification from what the rulebook stored", () => {
    const report = citationReportFromDto({
      added: 1,
      unchanged: 0,
      citations: [citationDto(), citationDto({ citation_id: "c2", quote: "Example other" })],
    });
    expect(
      citationsResult(report, [
        { clauseId: EXAMPLE_CLAUSE_IDS.first, quote: "Example clause text that opens" },
        { clauseId: EXAMPLE_CLAUSE_IDS.second, quote: "Example missing" },
      ]),
    ).toEqual({
      added: 1,
      unchanged: 0,
      verified: [
        {
          clauseRef: "en.p1",
          quote: "Example clause text that opens",
          verified: true,
          matchScore: 0.97,
        },
      ],
    });
  });
});
