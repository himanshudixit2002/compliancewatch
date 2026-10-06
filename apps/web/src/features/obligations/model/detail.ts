import type { Tone } from "@compliancewatch/ui";
import type { Applicability, Decision } from "@/entities/applicability/types";
import type {
  ObligationChange,
  ObligationDetail,
  ObligationStatus,
  StatusAction,
} from "@/entities/obligation/types";
import type { ClauseDetail } from "@/entities/rulebook/types";
import { t, type MessageKey } from "@/shared/i18n";
import { addDaysToKey, formatDate, formatDateTime } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { safeHttpUrl } from "@/shared/lib/url";
import type { CitationView } from "@/shared/ui/citation-list";
import {
  closedText,
  closureReasonLabel,
  dueDateText,
  duePhrase,
  evidenceTypeText,
  isObligationOverdue,
  obligationStatusLabel,
  obligationStatusTone,
  periodText,
  reviewState,
  statusActionLabel,
  statusActions,
  type ReviewState,
} from "./obligations";

/**
 * One obligation's page as it renders: what to do and by when, the rule it comes from with its
 * review state, the clauses it cites with their text, why it applies (the engine's latest
 * decision for its node and rule version, predicate by predicate), what has happened to it, the
 * comments, and what a member may do with it now. Every service fact is worded here; nothing in
 * the view decides.
 */
export interface PredicateView {
  attribute: string;
  description: string;
  outcome: string;
  tone: Tone;
  reason: string;
  confidence: string;
  needsReview: boolean;
}

export type WhyView =
  | {
      state: "decided";
      result: string;
      tone: Tone;
      confidence: string;
      decidedAt: string;
      /** True when the decision is not the one the obligation was made from. */
      later: boolean;
      needsReview: boolean;
      predicates: readonly PredicateView[];
      trigger: string;
      year: string | null;
    }
  | { state: "none" }
  | { state: "error"; message: string; correlationId: string | null };

export interface HistoryItem {
  id: string;
  when: string;
  dateTime: string;
  title: string;
  body: string | null;
  tone: Tone;
}

export interface CommentView {
  id: string;
  body: string;
  author: string;
  when: string;
  dateTime: string;
}

export interface ReviewView extends ReviewState {
  ruleTitle: string | null;
  /** "Published on 2 Jan 2026, approved by ..."; null when the version was never published. */
  approvedBy: readonly string[];
  publishedAt: string | null;
  effective: string | null;
}

export interface ObligationPageView {
  id: string;
  businessId: string;
  title: string;
  period: string | null;
  node: string;
  status: ObligationStatus;
  statusLabel: string;
  statusTone: Tone;
  due: string;
  dueNote: string | null;
  overdue: boolean;
  closed: string | null;
  evidence: string;
  steps: readonly string[];
  review: ReviewView;
  citations: readonly CitationView[];
  why: WhyView;
  history: readonly HistoryItem[];
  comments: readonly CommentView[];
  actions: readonly { action: StatusAction; label: string }[];
  assigneeId: string | null;
  /** Comments are taken on closed obligations too; the other changes are not. */
  open: boolean;
}

const RESULT_LABEL: Readonly<Record<Applicability, MessageKey>> = {
  applies: "obligation.why.applies",
  not_applicable: "obligation.why.notApplicable",
  unsure: "obligation.why.unsure",
};

const RESULT_TONE: Readonly<Record<Applicability, Tone>> = {
  applies: "success",
  not_applicable: "neutral",
  unsure: "warning",
};

const OUTCOME_LABEL: Readonly<Record<Applicability, MessageKey>> = {
  applies: "obligation.why.outcome.applies",
  not_applicable: "obligation.why.outcome.notApplicable",
  unsure: "obligation.why.outcome.unsure",
};

/** "92%": a confidence from 0 to 1, rounded. */
export function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function citationViews(
  detail: Pick<ObligationDetail, "citations">,
  clauses: ReadonlyMap<string, ClauseDetail>,
): CitationView[] {
  return detail.citations.map((citation) => {
    const clause = clauses.get(citation.clauseId);
    return {
      id: citation.citationId,
      clauseRef: citation.clauseRef,
      quote: citation.quote,
      clauseText: clause?.text ?? null,
      documentTitle: clause?.title ?? null,
      documentRef: clause?.externalRef ?? null,
      sourceHref: safeHttpUrl(clause?.url),
      page: clause?.page ?? null,
      verifiedAt: citation.verifiedAt === null ? null : formatDate(citation.verifiedAt),
    };
  });
}

export function whyView(
  decision: Decision | null,
  madeFrom: string,
): Extract<WhyView, { state: "decided" } | { state: "none" }> {
  if (decision === null) return { state: "none" };
  return {
    state: "decided",
    result: t(RESULT_LABEL[decision.result]),
    tone: RESULT_TONE[decision.result],
    confidence: percent(decision.confidence),
    decidedAt: formatDateTime(decision.decidedAt),
    later: decision.id !== madeFrom,
    needsReview: decision.needsReview,
    trigger: humanise(decision.trigger),
    year: decision.asOfFy,
    predicates: decision.evaluated.map((predicate) => ({
      attribute: predicate.attribute,
      description: predicate.description,
      outcome: t(OUTCOME_LABEL[predicate.outcome]),
      tone: RESULT_TONE[predicate.outcome],
      reason: predicate.reason,
      confidence: percent(predicate.confidence),
      needsReview: predicate.needsReview,
    })),
  };
}

function shortId(id: string): string {
  return id.slice(0, 8);
}

/** Who made a change: "you", a user by the start of their id, or the system. */
export function actorText(actor: string | null, viewerId: string): string {
  if (actor === null) return t("obligation.history.bySystem");
  if (actor === viewerId) return t("obligation.history.byYou");
  return t("obligation.history.byUser", { id: shortId(actor) });
}

function changeTitle(change: ObligationChange): string {
  switch (change.kind) {
    case "created":
      return t("obligation.history.created");
    case "started":
      return t("obligation.history.started");
    case "rescheduled":
      return t("obligation.history.rescheduled", {
        from:
          change.previousDueAt === null
            ? t("obligations.noDueDate")
            : formatDate(change.previousDueAt),
        to: change.newDueAt === null ? t("obligations.noDueDate") : formatDate(change.newDueAt),
      });
    case "closed":
      return t("obligation.history.closed", { status: obligationStatusLabel(change.statusAfter) });
    case "assigned":
      return t("obligation.history.assigned", {
        to: change.newAssigneeId === null ? "" : shortId(change.newAssigneeId),
      });
    case "unassigned":
      return t("obligation.history.unassigned");
  }
}

function changeBody(change: ObligationChange, viewerId: string): string {
  const parts = [actorText(change.actor, viewerId)];
  if (change.kind === "closed" && change.reason !== "") {
    const reason = change.reason as Parameters<typeof closureReasonLabel>[0];
    parts.push(closureReasonLabel(reason));
  }
  if (change.note !== "") parts.push(t("obligation.history.note", { note: change.note }));
  return parts.join(". ");
}

export function historyItems(
  history: readonly ObligationChange[],
  viewerId: string,
): HistoryItem[] {
  return history.map((change) => ({
    id: change.id,
    when: formatDateTime(change.occurredAt),
    dateTime: change.occurredAt,
    title: changeTitle(change),
    body: changeBody(change, viewerId),
    tone: change.kind === "closed" ? obligationStatusTone(change.statusAfter) : "neutral",
  }));
}

export function reviewView(detail: Pick<ObligationDetail, "ruleVersion">): ReviewView {
  const facts = detail.ruleVersion;
  return {
    ...reviewState(facts),
    ruleTitle: facts?.title ?? null,
    approvedBy: facts?.approvedBy ?? [],
    publishedAt:
      facts?.publishedAt === null || facts === null ? null : formatDate(facts.publishedAt),
    effective:
      facts === null
        ? null
        : facts.effectiveTo === null
          ? t("obligation.rule.effectiveFrom", { from: formatDate(facts.effectiveFrom) })
          : // The end is exclusive: the version's last day is the day before it.
            t("obligation.rule.effectiveBetween", {
              from: formatDate(facts.effectiveFrom),
              to: formatDate(addDaysToKey(facts.effectiveTo, -1)),
            }),
  };
}

export function obligationPageView(
  detail: ObligationDetail,
  options: {
    node: string;
    clauses: ReadonlyMap<string, ClauseDetail>;
    why: WhyView;
    viewerId: string;
    now?: Date;
  },
): ObligationPageView {
  const now = options.now ?? new Date();
  return {
    id: detail.id,
    businessId: detail.businessId,
    title: detail.title,
    period: periodText(detail),
    node: options.node,
    status: detail.status,
    statusLabel: obligationStatusLabel(detail.status),
    statusTone: obligationStatusTone(detail.status),
    due: dueDateText(detail),
    dueNote: duePhrase(detail, now),
    overdue: isObligationOverdue(detail, now),
    closed: closedText(detail),
    evidence: evidenceTypeText(detail.evidenceType),
    steps: detail.steps,
    review: reviewView(detail),
    citations: citationViews(detail, options.clauses),
    why: options.why,
    history: historyItems(detail.history, options.viewerId),
    comments: detail.comments.map((comment) => ({
      id: comment.id,
      body: comment.body,
      author:
        comment.authorId !== null && comment.authorId === options.viewerId
          ? t("obligation.comments.you")
          : humanise(comment.authorLabel),
      when: formatDateTime(comment.createdAt),
      dateTime: comment.createdAt,
    })),
    actions: statusActions(detail.status).map((action) => ({
      action,
      label: statusActionLabel(action),
    })),
    assigneeId: detail.assigneeId,
    open: statusActions(detail.status).length > 0,
  };
}

/** A user of the tenant as the assignee picker lists them. */
export interface MemberRef {
  id: string;
  name: string;
  roles: readonly string[];
}

/** Who an obligation is given to, as people read it: you, a member by name, or a user id. */
export function assigneeText(
  assigneeId: string | null,
  viewerId: string,
  members: readonly MemberRef[] = [],
): string {
  if (assigneeId === null) return t("obligation.assignee.nobodyShort");
  if (assigneeId === viewerId) return t("obligation.assignee.you");
  const member = members.find((candidate) => candidate.id === assigneeId);
  return member === undefined ? t("obligation.assignee.user", { id: assigneeId }) : member.name;
}

/** "Example owner (Owner)": a member with their roles, for the picker. */
export function memberLabel(member: MemberRef): string {
  return member.roles.length === 0
    ? member.name
    : t("obligation.assignee.memberLabel", {
        name: member.name,
        roles: member.roles.map((role) => humanise(role)).join(", "),
      });
}
