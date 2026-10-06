import type { AnswerDto } from "@/entities/answer/types";
import { DOCUMENT_ID } from "./obligation-fixture";

/** Answers of the public ask for unit tests: synthetic wording, dates in 2000. */
export function answerDto(overrides: Partial<AnswerDto> = {}): AnswerDto {
  return {
    outcome: "answered",
    answer: "Example answer: due on 20 Jan 2000.",
    citations: [
      { clause_ref: "en.p2", document_id: DOCUMENT_ID, quote: "Example quoted clause text." },
    ],
    layer: "structured",
    layers: [{ layer: "structured", result: "answered", reason: null }],
    plan: null,
    reason: null,
    as_of: "2000-01-10",
    ...overrides,
  };
}

export function notCoveredDto(overrides: Partial<AnswerDto> = {}): AnswerDto {
  return answerDto({
    outcome: "not_covered",
    answer: "Example fixed sentence for a question that is not covered.",
    citations: [],
    layer: "hybrid",
    layers: [
      { layer: "structured", result: "passed", reason: null },
      { layer: "hybrid", result: "not_covered", reason: "no_evidence" },
    ],
    reason: "no_evidence",
    ...overrides,
  });
}
