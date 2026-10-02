import type { SelectOption, Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";

/** Whether a regulatory change applies to the business, as the applicability engine judged it. */
export type ChangeApplicability = "applies" | "does_not_apply" | "pending" | "unknown";

/** Where the rule version stands in the rulebook's editorial review. */
export type ChangeReviewStatus = "published" | "in_review" | "draft" | "rejected";

export const CHANGE_APPLICABILITIES: readonly ChangeApplicability[] = [
  "applies",
  "pending",
  "does_not_apply",
  "unknown",
];

export const CHANGE_REVIEW_STATUSES: readonly ChangeReviewStatus[] = [
  "published",
  "in_review",
  "draft",
  "rejected",
];

/** One regulatory change (a new rule version) as the changes screen lists it. */
export interface ChangeItem {
  id: string;
  title: string;
  regulator: string;
  /** Date key (YYYY-MM-DD) from which the rule applies. */
  effectiveDate: string;
  /** When the regulator published it: a date key or an instant. */
  publishedAt: string;
  applicability: ChangeApplicability;
  /** The engine's confidence from 0 to 1, or null when it has not judged yet. */
  confidence: number | null;
  reviewStatus: ChangeReviewStatus;
  categories: readonly string[];
  /** The title of the rule version this one replaces, if any. */
  supersedes: string | null;
  summary: string;
}

/** The figures in the screen's description. */
export interface ChangeCounts {
  total: number;
  applicable: number;
  inReview: number;
}

const APPLICABILITY_LABEL: Readonly<Record<ChangeApplicability, MessageKey>> = {
  applies: "changes.applicability.applies",
  does_not_apply: "changes.applicability.doesNotApply",
  pending: "changes.applicability.pending",
  unknown: "changes.applicability.unknown",
};

const APPLICABILITY_TONE: Readonly<Record<ChangeApplicability, Tone>> = {
  applies: "success",
  does_not_apply: "neutral",
  pending: "warning",
  unknown: "info",
};

const REVIEW_LABEL: Readonly<Record<ChangeReviewStatus, MessageKey>> = {
  published: "changes.review.published",
  in_review: "changes.review.inReview",
  draft: "changes.review.draft",
  rejected: "changes.review.rejected",
};

const REVIEW_TONE: Readonly<Record<ChangeReviewStatus, Tone>> = {
  published: "success",
  in_review: "warning",
  draft: "neutral",
  rejected: "danger",
};

/** Summaries longer than this many characters are cut and end with an ellipsis. */
export const SUMMARY_LIMIT = 200;

export function applicabilityLabel(applicability: ChangeApplicability): string {
  return t(APPLICABILITY_LABEL[applicability]);
}

export function applicabilityTone(applicability: ChangeApplicability): Tone {
  return APPLICABILITY_TONE[applicability];
}

export function reviewStatusLabel(status: ChangeReviewStatus): string {
  return t(REVIEW_LABEL[status]);
}

export function reviewStatusTone(status: ChangeReviewStatus): Tone {
  return REVIEW_TONE[status];
}

export function applicabilityOptions(): SelectOption[] {
  return CHANGE_APPLICABILITIES.map((value) => ({ value, label: applicabilityLabel(value) }));
}

export function reviewStatusOptions(): SelectOption[] {
  return CHANGE_REVIEW_STATUSES.map((value) => ({ value, label: reviewStatusLabel(value) }));
}

export function shortSummary(summary: string): string {
  if (summary.length <= SUMMARY_LIMIT) return summary;
  return `${summary.slice(0, SUMMARY_LIMIT).trimEnd()}…`;
}

/**
 * The worded facts under a change's summary: who issued it, when it takes effect and was
 * published, what it supersedes and how sure the engine is, leaving out what is unknown.
 */
export function changeFacts(change: ChangeItem): string[] {
  const facts = [
    t("changes.fact.regulator", { regulator: change.regulator }),
    t("changes.fact.effective", { date: formatDate(change.effectiveDate) }),
    t("changes.fact.published", { date: formatDate(change.publishedAt) }),
  ];
  if (change.supersedes !== null) {
    facts.push(t("changes.fact.supersedes", { title: change.supersedes }));
  }
  if (change.confidence !== null) {
    facts.push(t("changes.fact.confidence", { percent: Math.round(change.confidence * 100) }));
  }
  return facts;
}

export function changeCounts(changes: readonly ChangeItem[]): ChangeCounts {
  return {
    total: changes.length,
    applicable: changes.filter((change) => change.applicability === "applies").length,
    inReview: changes.filter((change) => change.reviewStatus === "in_review").length,
  };
}
