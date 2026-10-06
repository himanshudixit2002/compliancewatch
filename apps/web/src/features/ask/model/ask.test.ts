import { describe, expect, it } from "vitest";
import { answerFromDto } from "@/entities/answer/mappers";
import { businessFromDto } from "@/entities/business/mappers";
import { documentFromDto } from "@/entities/rulebook/mappers";
import { answerDto, notCoveredDto } from "@/test/answer-fixture";
import { BUSINESS_DTO, ENTITY_ID, REGISTRATION_ID } from "@/test/business-fixture";
import { DOCUMENT_ID } from "@/test/obligation-fixture";
import { documentDto } from "@/test/rulebook-fixture";
import {
  answerCitations,
  answerView,
  checkQuestion,
  layerLabel,
  nodeOptions,
  reasonLabel,
} from "./ask";

const FIELDS = { question: "question", node: "node_id" };

describe("nodeOptions", () => {
  it("offers the registrations first, then the business", () => {
    expect(nodeOptions(businessFromDto(BUSINESS_DTO))).toEqual([
      { id: REGISTRATION_ID, label: "29ABCDE1234F1Z5 (Example registration)" },
      { id: ENTITY_ID, label: "Example business (PAN ABCDE1234F)" },
    ]);
  });
});

describe("checkQuestion", () => {
  const options = nodeOptions(businessFromDto(BUSINESS_DTO));

  it("takes a trimmed question about one of the business's nodes", () => {
    expect(checkQuestion("  Example question?  ", REGISTRATION_ID, options, FIELDS)).toEqual({
      ok: true,
      question: "Example question?",
      nodeId: REGISTRATION_ID,
    });
  });

  it("refuses an empty or a too long question and a node of another business", () => {
    expect(checkQuestion("   ", "other", options, FIELDS)).toEqual({
      ok: false,
      fieldErrors: {
        question: ["Write a question first."],
        node_id: ["Choose a registration or the business from the list."],
      },
    });
    expect(checkQuestion("x".repeat(1001), ENTITY_ID, options, FIELDS)).toEqual({
      ok: false,
      fieldErrors: { question: ["A question can be at most 1000 characters."] },
    });
  });
});

describe("answers", () => {
  it("labels the layer that decided and each reason", () => {
    expect(layerLabel("structured")).toBe("Answered from this business's obligations");
    expect(layerLabel("hybrid")).toBe("Answered from a search of the clauses in force");
    expect(reasonLabel("no_evidence")).toBe("no clause in force says enough to answer it");
    expect(reasonLabel("citation_check_failed")).toMatch(/withheld/);
  });

  it("joins each citation with its clause read from its document, by reference", () => {
    const document = documentFromDto(documentDto({ document_id: DOCUMENT_ID }));
    const clauseRef = document.clauses[0]?.clauseRef ?? "en.p1";
    const answer = answerFromDto(
      answerDto({
        citations: [{ clause_ref: clauseRef, document_id: DOCUMENT_ID, quote: "Example quote" }],
      }),
    );
    const [joined] = answerCitations(answer, new Map([[DOCUMENT_ID, document]]));
    expect(joined).toMatchObject({
      clauseRef,
      quote: "Example quote",
      clauseText: document.clauses[0]?.text,
      documentTitle: "Example document title",
      documentRef: "Example 1/2000",
      sourceHref: "https://example.com/example-document.pdf",
    });
    const [unread] = answerCitations(answer, new Map());
    expect(unread).toMatchObject({ clauseText: null, documentTitle: null, sourceHref: null });
  });

  it("words an answer and a question that is not covered, with every layer that ran", () => {
    const answered = answerView(answerFromDto(answerDto()), {
      question: "Example question?",
      about: "29ABCDE1234F1Z5 (Example registration)",
      documents: new Map(),
    });
    expect(answered).toMatchObject({
      outcome: "answered",
      outcomeLabel: "Answered",
      tone: "success",
      text: "Example answer: due on 20 Jan 2000.",
      layerLabel: "Answered from this business's obligations",
      reason: null,
      asOf: "10 Jan 2000",
    });
    expect(answered.layers).toEqual([
      {
        layer: "structured",
        label: "This business's obligations",
        result: "answered",
        reason: null,
      },
    ]);
    const notCovered = answerView(answerFromDto(notCoveredDto()), {
      question: "Example question?",
      about: "x",
      documents: new Map(),
    });
    expect(notCovered).toMatchObject({
      outcome: "not_covered",
      outcomeLabel: "Not covered",
      tone: "neutral",
      reason: "no clause in force says enough to answer it",
      citations: [],
    });
    expect(notCovered.layers.map((run) => `${run.label}: ${run.result}`)).toEqual([
      "This business's obligations: did not apply",
      "A search of the clauses in force: not covered",
    ]);
  });
});
