import {
  CANDIDATE_REJECT_REASONS,
  RULE_VERSION_ONLY_RELATIONS,
  type CandidateRejectReason,
  type ClauseDetail,
  type RelationCandidate,
} from "@/entities/rulebook/types";
import type { RuleVersion } from "@/entities/rule-version/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { humanise } from "@/shared/lib/humanise";
import { isHexUuid } from "@/shared/lib/identifiers";
import { withQuery } from "@/shared/lib/url";
import {
  candidateRejectReasonLabel,
  type CandidateDecisionResult,
  type VersionOption,
} from "../ui/decision-shared";
import {
  candidateStatusLabel,
  evidenceHref,
  isCandidateStatus,
  percent,
  periodText,
} from "./queue";

/**
 * One relation candidate's page. No route reads a candidate by its id, so the page reads it from
 * the list the queue pages through: the list is in id order and `after` is exclusive, so asking
 * for one candidate after the id just before this one returns this one, if it is in the status
 * asked (D-055). The status the queue listed it in is tried first, then the other two.
 */
const UUID_HEX = 32;

/** The UUID just before this one in the rulebook's id order, or null for the nil UUID. */
export function predecessorOf(uuid: string): string | null {
  if (!isHexUuid(uuid)) return null;
  const value = BigInt(`0x${uuid.replace(/-/g, "")}`);
  if (value === 0n) return null;
  const hex = (value - 1n).toString(16).padStart(UUID_HEX, "0");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** The statuses to look in, the one the address names first. */
export function lookupOrder(
  hint: string | undefined,
): readonly ("open" | "approved" | "rejected")[] {
  const all = ["open", "approved", "rejected"] as const;
  if (hint === undefined || !isCandidateStatus(hint)) return all;
  return [hint, ...all.filter((status) => status !== hint)];
}

/**
 * Whether approving needs the affected rule version: the relations that only point at a version
 * (supersedes, extends a deadline, corrects, withdraws), and any candidate that names its target
 * rule's key. The rulebook says so with a 422 too; the form says it first.
 */
export function needsTargetVersion(
  candidate: Pick<RelationCandidate, "relation" | "targetRuleKey">,
): boolean {
  return (
    (RULE_VERSION_ONLY_RELATIONS as readonly string[]).includes(candidate.relation) ||
    candidate.targetRuleKey !== null
  );
}

/** A quote cut out of its clause, when the clause holds it word for word. */
export interface QuoteMark {
  before: string;
  mark: string;
  after: string;
}

export function markQuote(text: string, quote: string): QuoteMark | null {
  const at = quote === "" ? -1 : text.indexOf(quote);
  if (at < 0) return null;
  return {
    before: text.slice(0, at),
    mark: text.slice(at, at + quote.length),
    after: text.slice(at + quote.length),
  };
}

function isRejectReason(value: string): value is CandidateRejectReason {
  return (CANDIDATE_REJECT_REASONS as readonly string[]).includes(value);
}

/** The reason a closed candidate was rejected, in words; one this app does not know as sent. */
export function rejectReasonText(reason: string | null): string | null {
  if (reason === null || reason === "") return null;
  return isRejectReason(reason) ? candidateRejectReasonLabel(reason) : humanise(reason);
}

export interface CandidateFacts {
  candidateId: string;
  relationLabel: string;
  targetTypeLabel: string;
  targetName: string;
  targetRuleKey: string | null;
  targetEntityId: string | null;
  /** The entity's page when the target is aligned. */
  targetEntityHref: string | null;
  /** The entity review group of the target's name, while it is not aligned. */
  targetGroupHref: string | null;
  period: string | null;
  quoteScore: string;
  confidence: string;
  needsReview: boolean;
  issues: readonly { code: string; label: string; detail: string }[];
  model: string;
  promptVersion: string;
  status: string;
  statusLabel: string;
  open: boolean;
  decidedBy: string;
  rejectReasonLabel: string | null;
  documentId: string;
}

export function candidateFacts(candidate: RelationCandidate): CandidateFacts {
  return {
    candidateId: candidate.candidateId,
    relationLabel: humanise(candidate.relation),
    targetTypeLabel: humanise(candidate.targetType),
    targetName: candidate.targetName,
    targetRuleKey: candidate.targetRuleKey,
    targetEntityId: candidate.targetEntityId,
    targetEntityHref:
      candidate.targetEntityId === null
        ? null
        : hrefFor(screenById("admin.rulebook.canonical.entity"), {
            entityId: candidate.targetEntityId,
          }),
    targetGroupHref:
      candidate.targetEntityId === null
        ? withQuery(hrefFor(screenById("admin.rulebook.entities.group")), {
            type: candidate.targetType,
            name: candidate.targetName,
          })
        : null,
    period: periodText(candidate),
    quoteScore: percent(candidate.quoteScore),
    confidence: percent(candidate.confidence),
    needsReview: candidate.needsReview,
    issues: candidate.issues.map((issue) => ({
      code: issue.code,
      label: humanise(issue.code),
      detail: issue.detail,
    })),
    model: candidate.model,
    promptVersion: candidate.promptVersion,
    status: candidate.status,
    statusLabel: candidateStatusLabel(candidate.status),
    open: candidate.status === "open",
    decidedBy: candidate.decidedBy,
    rejectReasonLabel: rejectReasonText(candidate.rejectReason),
    documentId: candidate.documentId,
  };
}

export interface Evidence {
  quote: string;
  /** The clause with the quote marked; null when the clause could not be read or lacks it. */
  mark: QuoteMark | null;
  clauseRef: string | null;
  documentTitle: string | null;
  /** The document viewer with the clause marked. */
  href: string;
}

export function evidenceOf(candidate: RelationCandidate, clause: ClauseDetail | null): Evidence {
  return {
    quote: candidate.evidenceQuote,
    mark: clause === null ? null : markQuote(clause.text, candidate.evidenceQuote),
    clauseRef: clause?.clauseRef ?? null,
    documentTitle: clause === null ? null : clause.title || clause.externalRef,
    href: evidenceHref(candidate.documentId, candidate.evidenceClauseId),
  };
}

function versionLabel(version: RuleVersion): string {
  return t("relationReview.versionOption", {
    rule: version.ruleKey,
    version: version.version,
    status: humanise(version.status),
    title: version.title,
  });
}

function byKeyAndNumber(a: RuleVersion, b: RuleVersion): number {
  return a.ruleKey.localeCompare(b.ruleKey) || a.version - b.version;
}

/**
 * What the approve form offers. The version the relation starts from must be a draft that is
 * not closed (a closed draft's rule candidate was rejected: it never moves on). The target is a
 * version of the rule the candidate names, or of any rule when it names none; a closed draft is
 * never offered there either.
 */
export function versionOptions(
  versions: readonly RuleVersion[],
  targetRuleKey: string | null,
): { from: VersionOption[]; target: VersionOption[] } {
  const sorted = [...versions].filter((version) => !version.closed).sort(byKeyAndNumber);
  return {
    from: sorted
      .filter((version) => version.status === "draft")
      .map((version) => ({ value: version.ruleVersionId, label: versionLabel(version) })),
    target: sorted
      .filter((version) => targetRuleKey === null || version.ruleKey === targetRuleKey)
      .map((version) => ({ value: version.ruleVersionId, label: versionLabel(version) })),
  };
}

/** What an approval answered, as the panel says it. */
export function approvedResult(
  ruleRelationId: string,
  fromRuleVersionId: string,
): CandidateDecisionResult {
  return {
    kind: "decided",
    message: t("relationReview.approved", { id: ruleRelationId }),
    ruleRelationId,
    graphHref: withQuery(hrefFor(screenById("admin.rulebook.relations.graph")), {
      rule_version_id: fromRuleVersionId,
    }),
  };
}

export function rejectedResult(reasonLabel: string): CandidateDecisionResult {
  return {
    kind: "decided",
    message: t("relationReview.rejected", { reason: reasonLabel }),
    ruleRelationId: null,
    graphHref: null,
  };
}

/**
 * A candidate found decided after the rulebook refused a decision as already made: who decided
 * it ("you" for the signed-in analyst) and how, as information rather than a failure.
 */
export function alreadyDecidedResult(
  candidate: Pick<RelationCandidate, "status" | "decidedBy" | "rejectReason">,
  userId: string,
): CandidateDecisionResult {
  const who =
    candidate.decidedBy === ""
      ? t("relationReview.already.unknown")
      : candidate.decidedBy === userId
        ? t("relationReview.already.you")
        : candidate.decidedBy;
  const message =
    candidate.status === "approved"
      ? t("relationReview.already.approved", { who })
      : candidate.status === "rejected"
        ? t("relationReview.already.rejected", {
            who,
            reason:
              rejectReasonText(candidate.rejectReason) ?? t("relationReview.already.noReason"),
          })
        : t("relationReview.already.other", {
            who,
            status: candidateStatusLabel(candidate.status),
          });
  return { kind: "already", message, ruleRelationId: null, graphHref: null };
}
