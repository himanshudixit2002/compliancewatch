import type { Tone } from "@compliancewatch/ui";
import type {
  Applicability,
  PredicateKind,
  Resolution,
  ReviewItem,
  ReviewReason,
  ReviewStatus,
} from "@/entities/applicability/types";
import type { RuleVersion } from "@/entities/rule-version/types";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";

/**
 * A review item in words: what is under review (the rule version, named from the rulebook, and the
 * node it was decided for), why a person has to look (a condition in words nobody judged, or a
 * judgement below the threshold), the decision with every condition's outcome as the engine
 * describes it, and, once settled, the resolution, who settled it, when and why.
 */
export const REVIEW_PAGE_SIZE = 20;

const REASON_LABEL: Readonly<Record<ReviewReason, MessageKey>> = {
  free_text: "decisions.reason.free_text",
  low_confidence: "decisions.reason.low_confidence",
};

const STATUS: Readonly<Record<ReviewStatus, { key: MessageKey; tone: Tone }>> = {
  open: { key: "decisions.status.open", tone: "warning" },
  resolved: { key: "decisions.status.resolved", tone: "success" },
};

const RESOLUTION_LABEL: Readonly<Record<Resolution, MessageKey>> = {
  applies: "decisions.resolution.applies",
  not_applicable: "decisions.resolution.not_applicable",
  dismiss: "decisions.resolution.dismiss",
};

const KIND_LABEL: Readonly<Record<PredicateKind, MessageKey>> = {
  structured: "decisions.kind.structured",
  free_text: "decisions.kind.free_text",
};

export const RESOLUTIONS: readonly Resolution[] = ["applies", "not_applicable", "dismiss"];

export function resolutionLabel(resolution: Resolution): string {
  return t(RESOLUTION_LABEL[resolution]);
}

/** "92%": a confidence from 0 to 1, rounded. */
export function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export interface PredicateRow {
  attribute: string;
  kind: string;
  description: string;
  outcome: Applicability;
  confidence: string;
  reason: string;
  needsReview: boolean;
}

export interface ReviewItemView {
  id: string;
  businessId: string;
  ruleVersionId: string;
  /** "example_rule v2" and the version's title, or the id when the rulebook did not answer. */
  versionName: string;
  versionTitle: string | null;
  versionHref: string;
  reason: string;
  status: ReviewStatus;
  statusLabel: string;
  statusTone: Tone;
  opened: string;
  openedIso: string;
  decision: {
    result: Applicability;
    needsReview: boolean;
    confidence: string;
    decided: string;
    trigger: string;
    profileVersion: number;
    year: string | null;
  };
  predicates: readonly PredicateRow[];
  /** Null while open. */
  resolution: {
    label: string;
    /** "you", a user by the start of their id, or a later decision that settled it. */
    by: string;
    at: string | null;
    note: string;
    decisionId: string | null;
  } | null;
}

function settledBy(resolvedBy: string | null, viewerId: string): string {
  if (resolvedBy === null) return t("decisions.by.laterDecision");
  if (resolvedBy === viewerId) return t("decisions.by.you");
  return t("decisions.by.user", { id: resolvedBy.slice(0, 8) });
}

/** How a resolved item was settled: by a reviewer's resolution, or by a later decision. */
function resolutionView(item: ReviewItem, viewerId: string): ReviewItemView["resolution"] {
  if (item.status === "open") return null;
  return {
    label:
      item.resolution === null
        ? t("decisions.resolution.superseded")
        : resolutionLabel(item.resolution),
    by: settledBy(item.resolvedBy, viewerId),
    at: item.resolvedAt === null ? null : formatDateTime(item.resolvedAt),
    note: item.note,
    decisionId: item.resolutionDecisionId,
  };
}

export function reviewItemView(
  item: ReviewItem,
  options: { version: RuleVersion | null; versionHref: string; viewerId: string },
): ReviewItemView {
  const { decision } = item;
  const { version } = options;
  return {
    id: item.id,
    businessId: item.businessId,
    ruleVersionId: item.ruleVersionId,
    versionName:
      version === null
        ? item.ruleVersionId
        : t("decisions.versionName", { rule: version.ruleKey, version: version.version }),
    versionTitle: version?.title ?? null,
    versionHref: options.versionHref,
    reason: t(REASON_LABEL[item.reason]),
    status: item.status,
    statusLabel: t(STATUS[item.status].key),
    statusTone: STATUS[item.status].tone,
    opened: formatDateTime(item.openedAt),
    openedIso: item.openedAt,
    decision: {
      result: decision.result,
      needsReview: decision.needsReview,
      confidence: percent(decision.confidence),
      decided: formatDateTime(decision.decidedAt),
      trigger: humanise(decision.trigger),
      profileVersion: decision.profileVersion,
      year: decision.asOfFy,
    },
    predicates: decision.evaluated.map((predicate) => ({
      attribute: predicate.attribute,
      kind: t(KIND_LABEL[predicate.kind]),
      description: predicate.description,
      outcome: predicate.outcome,
      confidence: percent(predicate.confidence),
      reason: predicate.reason,
      needsReview: predicate.needsReview,
    })),
    resolution: resolutionView(item, options.viewerId),
  };
}
