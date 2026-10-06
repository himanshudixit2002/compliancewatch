import type { qa } from "@compliancewatch/contracts/openapi";

/**
 * An answer from the public API's ask (`POST /v1/qa`). The layers answer in turn, cheapest first
 * (ADR-012): the business's own obligations (structured), the knowledge graph when it is on for
 * the tenant (kag), then a search of the clauses in force (hybrid). `answered` comes with at
 * least one citation whose quote was checked against its clause; `not_covered` with a fixed
 * sentence and the reason. `layers` lists every layer that ran.
 */
type Schemas = qa.components["schemas"];

export type AskInDto = Schemas["AskIn"];
export type AnswerDto = Schemas["AskOut"];
export type AnswerLayer = Schemas["Layer"];
export type LayerResult = Schemas["LayerResult"];
export type AnswerOutcome = Schemas["Outcome"];
export type NotCoveredReason = Schemas["Reason"];

export const ANSWER_LAYERS: readonly AnswerLayer[] = ["structured", "kag", "hybrid"];

/** The longest question the service takes. */
export const MAX_QUESTION_LENGTH = 1000;

export interface AnswerCitation {
  clauseRef: string;
  documentId: string;
  /** Verbatim from the clause, checked before it was returned. */
  quote: string;
}

export interface LayerRun {
  layer: AnswerLayer;
  result: LayerResult;
  reason: NotCoveredReason | null;
}

export interface Answer {
  outcome: AnswerOutcome;
  /** The answer, or the service's fixed sentence when the question is not covered. */
  text: string;
  citations: readonly AnswerCitation[];
  /** The layer that decided. */
  layer: AnswerLayer;
  layers: readonly LayerRun[];
  reason: NotCoveredReason | null;
  /** The date the answer is about, a date key. */
  asOf: string;
}

export interface Question {
  text: string;
  /** The profile node the question is about: a registration for its returns. */
  nodeId: string;
}
