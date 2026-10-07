import type { Ontology } from "@/entities/ontology/types";
import {
  obligationTemplateFromMapping,
  recurrenceFromMapping,
  specificationFromMapping,
} from "@/entities/rule-version/mappers";
import {
  RULE_REJECT_REASONS,
  type RuleCandidate,
  type RuleCandidateStatus,
  type RuleRejectReason,
} from "@/entities/rule-version/types";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { describeSpecification, type SpecLine } from "@/shared/ui/specification";
import { dueInDaysWords, periodWords, recurrenceWords } from "./content";
import { percent, personRef, type PersonRef } from "./queue";

/**
 * The candidate pane of a candidate task: what the pipeline's extraction made of the document
 * (the outcome and confidence, the model and prompt that made it, whether it asked for review and
 * what the validators found), why it looks high impact, the rule key it suggests and whether a
 * rule has it, and the draft it proposes field by field with each problem the rulebook found
 * mapping it. An unparseable candidate has no draft to propose: the analyst drafts by hand.
 */
const STATUS_LABELS: Readonly<Record<RuleCandidateStatus, MessageKey>> = {
  open: "workbench.candidate.status.open",
  drafted: "workbench.candidate.status.drafted",
  approved: "workbench.candidate.status.approved",
  rejected: "workbench.candidate.status.rejected",
};

export function candidateStatusLabel(status: string): string {
  return status in STATUS_LABELS
    ? t(STATUS_LABELS[status as RuleCandidateStatus])
    : humanise(status);
}

const REASON_LABELS: Readonly<Record<RuleRejectReason, MessageKey>> = {
  not_a_rule: "workbench.rejectReason.not_a_rule",
  wrong_extraction: "workbench.rejectReason.wrong_extraction",
  duplicate: "workbench.rejectReason.duplicate",
  out_of_scope: "workbench.rejectReason.out_of_scope",
  unparseable: "workbench.rejectReason.unparseable",
};

export function rejectReasonLabel(reason: string): string {
  return (RULE_REJECT_REASONS as readonly string[]).includes(reason)
    ? t(REASON_LABELS[reason as RuleRejectReason])
    : humanise(reason);
}

export interface ProposalView {
  title: string | null;
  summary: string | null;
  period: string;
  recurrence: string;
  template: {
    title: string;
    steps: readonly string[];
    due: string | null;
    evidence: string;
  } | null;
  /** The proposed condition in words; null when the candidate maps none. */
  specification: SpecLine | null;
  citations: readonly { clauseRef: string; quote: string }[];
  /** Each field that does not map, and why, as the rulebook states it. */
  problems: readonly string[];
}

export interface CandidatePane {
  candidateId: string;
  unparseable: boolean;
  outcome: string;
  confidence: string;
  model: string;
  promptVersion: string;
  needsReview: boolean;
  status: string;
  citationCount: number;
  createdAt: string;
  issues: readonly { code: string; clauseRef: string | null; detail: string }[];
  highImpactSuggested: boolean;
  highImpactReasons: readonly string[];
  suggestedKey: string | null;
  suggestedKnown: boolean;
  proposal: ProposalView;
  /** Who decided the candidate, when it was decided. */
  decided: { by: PersonRef | null; at: string | null; reason: string | null } | null;
  facts: readonly { label: string; value: string }[];
}

function proposalView(candidate: RuleCandidate, ontology: Ontology | null): ProposalView {
  const proposed = candidate.proposed;
  const template = obligationTemplateFromMapping(proposed.obligationTemplate);
  const specification =
    proposed.specification === null ? null : specificationFromMapping(proposed.specification);
  return {
    title: proposed.title,
    summary: proposed.summary,
    period: periodWords(proposed.effectiveFrom, proposed.effectiveTo),
    recurrence: recurrenceWords(recurrenceFromMapping(proposed.recurrence)),
    template:
      template === null
        ? null
        : {
            title: template.title,
            steps: template.steps,
            due:
              recurrenceFromMapping(proposed.recurrence) === null ? dueInDaysWords(template) : null,
            evidence:
              template.evidenceType === null || template.evidenceType === ""
                ? t("common.none")
                : humanise(template.evidenceType),
          },
    specification: specification === null ? null : describeSpecification(specification, ontology),
    citations: proposed.citations.map((citation) => ({
      clauseRef: citation.clauseRef,
      quote: citation.quote,
    })),
    problems: proposed.problems,
  };
}

export function candidatePane(
  candidate: RuleCandidate,
  ontology: Ontology | null,
  sessionUserId: string,
): CandidatePane {
  const decided =
    candidate.decidedAt === null && candidate.decidedBy === null
      ? null
      : {
          by: candidate.decidedBy === null ? null : personRef(candidate.decidedBy, sessionUserId),
          at: candidate.decidedAt === null ? null : formatDateTime(candidate.decidedAt),
          reason:
            candidate.rejectReason === null ? null : rejectReasonLabel(candidate.rejectReason),
        };
  return {
    candidateId: candidate.candidateId,
    unparseable: candidate.outcome === "unparseable",
    outcome:
      candidate.outcome === "unparseable"
        ? t("workbench.candidate.unparseable")
        : t("workbench.candidate.extracted"),
    confidence: percent(candidate.confidence),
    model: candidate.model,
    promptVersion: candidate.promptVersion,
    needsReview: candidate.needsReview,
    status: candidateStatusLabel(candidate.status),
    citationCount: candidate.citationCount,
    createdAt: formatDateTime(candidate.createdAt),
    issues: candidate.issues,
    highImpactSuggested: candidate.highImpactSuggested,
    highImpactReasons: candidate.highImpactReasons,
    suggestedKey: candidate.suggestedRuleKey,
    suggestedKnown: candidate.suggestedRuleKnown,
    proposal: proposalView(candidate, ontology),
    decided,
    facts: [
      ...(candidate.sourceKey === null
        ? []
        : [{ label: t("workbench.candidate.source"), value: candidate.sourceKey }]),
      ...(candidate.docType === null
        ? []
        : [{ label: t("workbench.candidate.docType"), value: humanise(candidate.docType) }]),
      ...(candidate.ontologyVersion === null
        ? []
        : [{ label: t("workbench.candidate.ontology"), value: candidate.ontologyVersion }]),
    ],
  };
}
