import type { Answer, AnswerLayer, LayerResult, NotCoveredReason } from "@/entities/answer/types";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { safeHttpUrl } from "@/shared/lib/url";
import type { CitationView } from "@/shared/ui/citation-list";
import { QUESTION_MAX_LENGTH, type AnswerView } from "../ui/answer-shared";
import type { Business, RulebookDocumentLike } from "./types";

/**
 * The ask screen's words: the layer that decided (ADR-012: the business's own obligations, the
 * knowledge graph, a search of the clauses in force), what each layer that ran did, why a
 * question is not covered, and the nodes a question can be about. The answer's text and its
 * quotes are the service's; nothing here rewrites them.
 */
const LAYER_LABEL: Readonly<Record<AnswerLayer, MessageKey>> = {
  structured: "ask.layer.structured",
  kag: "ask.layer.kag",
  hybrid: "ask.layer.hybrid",
};

const LAYER_NAME: Readonly<Record<AnswerLayer, MessageKey>> = {
  structured: "ask.layerName.structured",
  kag: "ask.layerName.kag",
  hybrid: "ask.layerName.hybrid",
};

const RESULT_LABEL: Readonly<Record<LayerResult, MessageKey>> = {
  answered: "ask.result.answered",
  not_covered: "ask.result.notCovered",
  passed: "ask.result.passed",
  fallback: "ask.result.fallback",
};

const REASON_LABEL: Readonly<Record<NotCoveredReason, MessageKey>> = {
  plan_invalid: "ask.reason.planInvalid",
  planner_unavailable: "ask.reason.plannerUnavailable",
  planner_deferred: "ask.reason.plannerDeferred",
  step_budget_exceeded: "ask.reason.stepBudgetExceeded",
  step_failed: "ask.reason.stepFailed",
  no_evidence: "ask.reason.noEvidence",
  answerer_declined: "ask.reason.answererDeclined",
  citation_check_failed: "ask.reason.citationCheckFailed",
};

export function layerLabel(layer: AnswerLayer): string {
  return t(LAYER_LABEL[layer]);
}

export function reasonLabel(reason: NotCoveredReason): string {
  return t(REASON_LABEL[reason]);
}

/** A node a question can be about: a registration (its returns), or the business itself. */
export interface NodeOption {
  id: string;
  label: string;
}

/**
 * The nodes a question can be about, registrations first: a GSTIN's returns are kept for its
 * registration, so a question about a return is asked of it.
 */
export function nodeOptions(business: Business): NodeOption[] {
  return [
    ...business.registrations.map((node) => ({
      id: node.id,
      label: t("business.node.registration", { key: node.key, name: node.name }),
    })),
    {
      id: business.id,
      label: t("business.node.entity", { key: business.pan, name: business.name }),
    },
  ];
}

export type QuestionCheck =
  | { ok: true; question: string; nodeId: string }
  | { ok: false; fieldErrors: Record<string, string[]> };

/** The form's shape: a question of 1 to 1000 characters, about one of the business's nodes. */
export function checkQuestion(
  question: string,
  nodeId: string,
  options: readonly NodeOption[],
  fields: { question: string; node: string },
): QuestionCheck {
  const errors: Record<string, string[]> = {};
  const text = question.trim();
  if (text === "") errors[fields.question] = [t("ask.question.empty")];
  else if (text.length > QUESTION_MAX_LENGTH) {
    errors[fields.question] = [t("ask.question.tooLong", { max: QUESTION_MAX_LENGTH })];
  }
  if (!options.some((option) => option.id === nodeId))
    errors[fields.node] = [t("ask.node.unknown")];
  return Object.keys(errors).length === 0
    ? { ok: true, question: text, nodeId }
    : { ok: false, fieldErrors: errors };
}

/** Each citation with its clause read from its document, by the clause's reference. */
export function answerCitations(
  answer: Pick<Answer, "citations">,
  documents: ReadonlyMap<string, RulebookDocumentLike>,
): CitationView[] {
  return answer.citations.map((citation, index) => {
    const document = documents.get(citation.documentId);
    const clause = document?.clauses.find(
      (candidate) => candidate.clauseRef === citation.clauseRef,
    );
    return {
      id: `${citation.documentId}-${citation.clauseRef}-${index}`,
      clauseRef: citation.clauseRef,
      quote: citation.quote,
      clauseText: clause?.text ?? null,
      documentTitle: document?.title ?? null,
      documentRef: document?.externalRef ?? null,
      sourceHref: safeHttpUrl(document?.url),
      page: clause?.page ?? null,
      verifiedAt: null,
    };
  });
}

export function answerView(
  answer: Answer,
  options: {
    question: string;
    about: string;
    documents: ReadonlyMap<string, RulebookDocumentLike>;
  },
): AnswerView {
  const answered = answer.outcome === "answered";
  return {
    question: options.question,
    about: options.about,
    outcome: answer.outcome,
    outcomeLabel: answered ? t("ask.outcome.answered") : t("ask.outcome.notCovered"),
    tone: answered ? "success" : "neutral",
    text: answer.text,
    layerLabel: layerLabel(answer.layer),
    reason: answer.reason === null ? null : reasonLabel(answer.reason),
    asOf: formatDate(answer.asOf),
    layers: answer.layers.map((run) => ({
      layer: run.layer,
      label: t(LAYER_NAME[run.layer]),
      result: t(RESULT_LABEL[run.result]),
      reason: run.reason === null ? null : reasonLabel(run.reason),
    })),
    citations: answerCitations(answer, options.documents),
  };
}
