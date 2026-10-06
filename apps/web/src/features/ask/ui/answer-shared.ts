import type { Tone } from "@compliancewatch/ui";
import type { CitationView } from "@/shared/ui/citation-list";

/**
 * What the ask form and its server action share, in the ui directory so the client form may
 * import it: the field names, the limits, and the answer as the form shows it, already worded.
 */
export const ASK_FIELDS = {
  businessId: "business_id",
  question: "question",
  node: "node_id",
} as const;

/** The longest question the qa service takes. */
export const QUESTION_MAX_LENGTH = 1000;

export interface LayerRunView {
  layer: string;
  label: string;
  result: string;
  reason: string | null;
}

export interface AnswerView {
  /** The question as asked, so the answer says what it answers. */
  question: string;
  /** The node the question was about, by its GSTIN or PAN. */
  about: string;
  outcome: "answered" | "not_covered";
  outcomeLabel: string;
  tone: Tone;
  /** The answer, or the service's fixed sentence when it is not covered. */
  text: string;
  /** "Answered from this business's obligations": the layer that decided. */
  layerLabel: string;
  /** Why it is not covered, in words; null when answered. */
  reason: string | null;
  asOf: string;
  layers: readonly LayerRunView[];
  citations: readonly CitationView[];
}
