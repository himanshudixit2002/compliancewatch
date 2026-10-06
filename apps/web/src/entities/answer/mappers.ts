import type { Answer, AnswerDto, AskInDto, Question } from "./types";

export function answerFromDto(dto: AnswerDto): Answer {
  return {
    outcome: dto.outcome,
    text: dto.answer,
    citations: dto.citations.map((citation) => ({
      clauseRef: citation.clause_ref,
      documentId: citation.document_id,
      quote: citation.quote,
    })),
    layer: dto.layer,
    layers: dto.layers.map((run) => ({
      layer: run.layer,
      result: run.result,
      reason: run.reason ?? null,
    })),
    reason: dto.reason ?? null,
    asOf: dto.as_of,
  };
}

/** The body of a question: its text trimmed and the node it is about. */
export function questionToDto(question: Question): AskInDto {
  return { question: question.text.trim(), business_node_id: question.nodeId };
}
