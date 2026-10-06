import type { Tone } from "@compliancewatch/ui";
import type { Applicability, ImpactBusiness } from "@/entities/applicability/types";
import type { RuleChange, RuleChangeKind } from "@/entities/change/types";
import type { ClauseDetail } from "@/entities/rulebook/types";
import { t, type MessageKey } from "@/shared/i18n";
import { addDaysToKey, formatDate, formatDateTime } from "@/shared/lib/dates";
import { safeHttpUrl, withQuery } from "@/shared/lib/url";
import type { CitationView } from "@/shared/ui/citation-list";

/**
 * The changes screen's words: what happened to a rule version (published, superseded, withdrawn,
 * a due date moved), its dates, whether an analyst has reviewed it and who approved its
 * publication, its citations, and whether it applies to this business, read from the change's
 * impact: the tenant's businesses with their latest decision of the version, grouped under the
 * client (the legal entity) they belong to.
 */
export const CHANGES_PAGE_SIZE = 20;

const KIND_LABEL: Readonly<Record<RuleChangeKind, MessageKey>> = {
  published: "changes.kind.published",
  superseded: "changes.kind.superseded",
  withdrawn: "changes.kind.withdrawn",
  deadline_changed: "changes.kind.deadlineChanged",
};

const KIND_TONE: Readonly<Record<RuleChangeKind, Tone>> = {
  published: "info",
  superseded: "neutral",
  withdrawn: "danger",
  deadline_changed: "warning",
};

/** Whether a change applies to this business, as the impact route says, or why it cannot say. */
export type ChangeApplicability = Applicability | "not_decided" | "unknown";

const APPLICABILITY_LABEL: Readonly<Record<ChangeApplicability, MessageKey>> = {
  applies: "changes.applicability.applies",
  not_applicable: "changes.applicability.doesNotApply",
  unsure: "changes.applicability.unsure",
  not_decided: "changes.applicability.notDecided",
  unknown: "changes.applicability.unknown",
};

const APPLICABILITY_TONE: Readonly<Record<ChangeApplicability, Tone>> = {
  applies: "success",
  not_applicable: "neutral",
  unsure: "warning",
  not_decided: "neutral",
  unknown: "neutral",
};

const RESULT_WORD: Readonly<Record<Applicability, MessageKey>> = {
  applies: "changes.result.applies",
  not_applicable: "changes.result.notApplicable",
  unsure: "changes.result.unsure",
};

export function kindLabel(kind: RuleChangeKind): string {
  return t(KIND_LABEL[kind]);
}

export function kindTone(kind: RuleChangeKind): Tone {
  return KIND_TONE[kind];
}

export function applicabilityLabel(applicability: ChangeApplicability): string {
  return t(APPLICABILITY_LABEL[applicability]);
}

/**
 * What the impact says for this business: it applies when it applies to any of its nodes, is
 * unsure when the engine is unsure for one and sure for none, and does not apply when every node
 * decided says so. No decision of the version for the business is said as such.
 */
export function applicabilityOf(businesses: readonly ImpactBusiness[] | null): ChangeApplicability {
  if (businesses === null || businesses.length === 0) return "not_decided";
  if (businesses.some((business) => business.result === "applies")) return "applies";
  if (businesses.some((business) => business.result === "unsure")) return "unsure";
  return "not_applicable";
}

/** The impact of a change for this business: its nodes' decisions, or why there are none. */
export type ImpactForBusiness =
  | { state: "read"; businesses: readonly ImpactBusiness[] }
  | { state: "failed"; message: string; correlationId: string | null };

export interface ApplicabilityView {
  value: ChangeApplicability;
  label: string;
  tone: Tone;
  /** One line per node decided: "29AB… (Example registration): applies, decided 5 Jan 2026". */
  details: readonly string[];
  /** The impact read's failure, with its correlation id to quote. */
  failure: { message: string; correlationId: string | null } | null;
}

export function applicabilityView(
  impact: ImpactForBusiness,
  nodeName: (nodeId: string) => string,
): ApplicabilityView {
  if (impact.state === "failed") {
    return {
      value: "unknown",
      label: applicabilityLabel("unknown"),
      tone: APPLICABILITY_TONE.unknown,
      details: [],
      failure: { message: impact.message, correlationId: impact.correlationId },
    };
  }
  const value = applicabilityOf(impact.businesses);
  return {
    value,
    label: applicabilityLabel(value),
    tone: APPLICABILITY_TONE[value],
    details: impact.businesses.map((business) =>
      t("changes.decidedFor", {
        node: nodeName(business.businessId),
        result: t(RESULT_WORD[business.result]),
        date: formatDate(business.decidedAt),
      }),
    ),
    failure: null,
  };
}

/** The version's dates in words: in force from, until (the day before the exclusive end). */
export function effectiveText(change: Pick<RuleChange, "effectiveFrom" | "effectiveTo">): string {
  return change.effectiveTo === null
    ? t("changes.effectiveFrom", { from: formatDate(change.effectiveFrom) })
    : t("changes.effectiveBetween", {
        from: formatDate(change.effectiveFrom),
        to: formatDate(addDaysToKey(change.effectiveTo, -1)),
      });
}

/** "Due date moved to 25 Jan 2026 for the period 2026-01", for a deadline change. */
export function deadlineText(change: Pick<RuleChange, "deadline">): string | null {
  const { deadline } = change;
  if (deadline === null) return null;
  const date = deadline.newDueOn === null ? t("changes.noDate") : formatDate(deadline.newDueOn);
  return deadline.periodLabel === null
    ? t("changes.deadlineMoved", { date })
    : t("changes.deadlineMovedFor", { date, period: deadline.periodLabel });
}

/** The versions the change acts on, counted in words; empty when it acts on none. */
export function relationsText(change: Pick<RuleChange, "relations">): string[] {
  const { relations } = change;
  const lines: string[] = [];
  if (relations.supersedes.length > 0) {
    lines.push(t("changes.relations.supersedes", { count: relations.supersedes.length }));
  }
  if (relations.corrects.length > 0) {
    lines.push(t("changes.relations.corrects", { count: relations.corrects.length }));
  }
  if (relations.withdraws.length > 0) {
    lines.push(t("changes.relations.withdraws", { count: relations.withdraws.length }));
  }
  if (relations.extendsDeadline.length > 0) {
    lines.push(t("changes.relations.extends", { count: relations.extendsDeadline.length }));
  }
  return lines;
}

export interface ChangeCardView {
  id: string;
  ruleVersionId: string;
  kind: RuleChangeKind;
  kindLabel: string;
  kindTone: Tone;
  title: string;
  summary: string;
  regulator: string;
  version: number;
  changedAt: string;
  changedAtIso: string;
  effective: string;
  deadline: string | null;
  relations: readonly string[];
  needsReview: boolean;
  approvedBy: readonly string[];
  publishedAt: string | null;
  citations: readonly CitationView[];
  applicability: ApplicabilityView;
}

export function changeCard(
  change: RuleChange,
  options: {
    clauses: ReadonlyMap<string, ClauseDetail>;
    applicability: ApplicabilityView;
  },
): ChangeCardView {
  return {
    id: change.id,
    ruleVersionId: change.ruleVersionId,
    kind: change.kind,
    kindLabel: kindLabel(change.kind),
    kindTone: kindTone(change.kind),
    title: change.title,
    summary: change.summary,
    regulator: change.regulator,
    version: change.version,
    changedAt: formatDateTime(change.changedAt),
    changedAtIso: change.changedAt,
    effective: effectiveText(change),
    deadline: deadlineText(change),
    relations: relationsText(change),
    needsReview: change.seedStatus !== "reviewed",
    approvedBy: change.approvedBy,
    publishedAt: change.publishedAt === null ? null : formatDate(change.publishedAt),
    citations: change.citations.map((citation, index) => {
      const clause = options.clauses.get(citation.clauseId);
      return {
        id: `${change.id}-${index}`,
        clauseRef: citation.clauseRef,
        quote: citation.quote,
        clauseText: clause?.text ?? null,
        documentTitle: clause?.title ?? null,
        documentRef: clause?.externalRef ?? null,
        sourceHref: safeHttpUrl(clause?.url),
        page: clause?.page ?? null,
        verifiedAt: null,
      };
    }),
    applicability: options.applicability,
  };
}

/** The feed's next page by the service's cursor, and back to the newest from a later one. */
export function feedHrefs(
  pathname: string,
  cursor: string | null,
  nextCursor: string | null,
): { nextHref: string | null; firstHref: string | null } {
  return {
    nextHref: nextCursor === null ? null : withQuery(pathname, { cursor: nextCursor }),
    firstHref: cursor === null ? null : pathname,
  };
}

/** The `cursor` of the address, when it is one the service could have written. */
export function readFeedCursor(value: string | string[] | undefined): string | null {
  const text = Array.isArray(value) ? value[0] : value;
  if (text === undefined || text === "" || text.length > 512) return null;
  return /^[A-Za-z0-9_-]+$/.test(text) ? text : null;
}
