import {
  CANDIDATE_STATUSES,
  type CandidateStatus,
  type RelationCandidate,
} from "@/entities/rulebook/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { isHexUuid } from "@/shared/lib/identifiers";
import { withQuery } from "@/shared/lib/url";
import type { FilterChip } from "@/shared/ui/filter-chips";

/**
 * The relation candidate queue: what the pipeline proposed a document says about a rule or an
 * entity (a deadline extended, a version superseded), in the rulebook's id order, one status at a
 * time, a page at a time. The query string holds the status, a document to narrow to and where the
 * page starts (the last candidate of the page before); ids are not personal data.
 *
 *   status    open (the default), approved or rejected
 *   document  one document's candidates (its id), or every document's
 *   after     continue after this candidate id
 */
export const CANDIDATE_PARAMS = { status: "status", document: "document", after: "after" } as const;

/** Rows a page shows; the gateway asks for one more to know whether another page follows. */
export const CANDIDATE_PAGE_SIZE = 25;

export interface CandidateFilter {
  status: CandidateStatus;
  documentId: string | null;
  after: string | null;
}

export type CandidateQueueRead =
  | { kind: "ok"; filter: CandidateFilter }
  /** The document id is malformed: nothing is read, and the field says why. */
  | { kind: "invalid"; value: string; filter: CandidateFilter };

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(query: Query, key: string): string {
  const value = query[key];
  return ((Array.isArray(value) ? value[0] : value) ?? "").trim();
}

export function isCandidateStatus(value: string): value is CandidateStatus {
  return (CANDIDATE_STATUSES as readonly string[]).includes(value);
}

export function readCandidateQueue(query: Query): CandidateQueueRead {
  const statusValue = first(query, CANDIDATE_PARAMS.status);
  const status = isCandidateStatus(statusValue) ? statusValue : "open";
  const document = first(query, CANDIDATE_PARAMS.document).toLowerCase();
  const after = first(query, CANDIDATE_PARAMS.after).toLowerCase();
  const cursor = isHexUuid(after) ? after : null;
  if (document !== "" && !isHexUuid(document)) {
    return { kind: "invalid", value: document, filter: { status, documentId: null, after: null } };
  }
  return {
    kind: "ok",
    filter: { status, documentId: document === "" ? null : document, after: cursor },
  };
}

export function candidateQueueHref(pathname: string, filter: CandidateFilter): string {
  return withQuery(pathname, {
    [CANDIDATE_PARAMS.status]: filter.status === "open" ? undefined : filter.status,
    [CANDIDATE_PARAMS.document]: filter.documentId ?? undefined,
    [CANDIDATE_PARAMS.after]: filter.after ?? undefined,
  });
}

const STATUS_LABELS: Readonly<Record<CandidateStatus, MessageKey>> = {
  open: "relationReview.status.open",
  approved: "relationReview.status.approved",
  rejected: "relationReview.status.rejected",
};

export function candidateStatusLabel(status: string): string {
  return isCandidateStatus(status) ? t(STATUS_LABELS[status]) : humanise(status);
}

/** One chip per status, each keeping the document filter and starting from the first page. */
export function statusChips(pathname: string, filter: CandidateFilter): FilterChip[] {
  return CANDIDATE_STATUSES.map((status) => ({
    key: status,
    label: candidateStatusLabel(status),
    href: candidateQueueHref(pathname, { status, documentId: filter.documentId, after: null }),
    current: status === filter.status,
  }));
}

/** A share in [0, 1] as a whole percentage: 0.875 reads "88%". */
export function percent(share: number): string {
  return `${Math.round(Math.min(Math.max(share, 0), 1) * 100)}%`;
}

/** A candidate's own page, with the status it was listed in, where the page looks for it first. */
export function candidateHref(candidateId: string, status: string): string {
  return withQuery(hrefFor(screenById("admin.rulebook.relation"), { candidateId }), {
    status: isCandidateStatus(status) ? status : undefined,
  });
}

/** The document viewer with the evidence clause marked (D-037). */
export function evidenceHref(documentId: string, clauseId: string): string {
  return withQuery(hrefFor(screenById("admin.rulebook.document"), { documentId }), {
    clause_id: clauseId,
  });
}

export interface CandidateRow {
  candidateId: string;
  href: string;
  relationLabel: string;
  targetLabel: string;
  targetName: string;
  /** Aligned to an entity, or still to be aligned in the entity review. */
  aligned: boolean;
  targetRuleKey: string | null;
  evidenceQuote: string;
  evidenceHref: string;
  quoteScore: string;
  confidence: string;
  needsReview: boolean;
  issues: readonly string[];
  /** "2000-01, due 21 Feb 2000" for a deadline extension; null otherwise. */
  period: string | null;
  status: string;
  statusLabel: string;
}

export function periodText(
  candidate: Pick<RelationCandidate, "periodLabel" | "newDueOn">,
): string | null {
  if (candidate.periodLabel === null && candidate.newDueOn === null) return null;
  if (candidate.newDueOn === null) return candidate.periodLabel;
  const due = formatDate(candidate.newDueOn);
  return candidate.periodLabel === null
    ? t("relationReview.dueOn", { date: due })
    : t("relationReview.periodDue", { period: candidate.periodLabel, date: due });
}

export function candidateRow(candidate: RelationCandidate): CandidateRow {
  return {
    candidateId: candidate.candidateId,
    href: candidateHref(candidate.candidateId, candidate.status),
    relationLabel: humanise(candidate.relation),
    targetLabel: humanise(candidate.targetType),
    targetName: candidate.targetName,
    aligned: candidate.targetEntityId !== null,
    targetRuleKey: candidate.targetRuleKey,
    evidenceQuote: candidate.evidenceQuote,
    evidenceHref: evidenceHref(candidate.documentId, candidate.evidenceClauseId),
    quoteScore: percent(candidate.quoteScore),
    confidence: percent(candidate.confidence),
    needsReview: candidate.needsReview,
    issues: candidate.issues.map((issue) => humanise(issue.code)),
    period: periodText(candidate),
    status: candidate.status,
    statusLabel: candidateStatusLabel(candidate.status),
  };
}

export interface CandidateQueueView {
  filter: CandidateFilter;
  rows: CandidateRow[];
  nextHref: string | null;
  firstHref: string | null;
}

/** The page from the candidates the rulebook returned (up to one more than a page). */
export function candidateQueueView(
  pathname: string,
  filter: CandidateFilter,
  candidates: readonly RelationCandidate[],
): CandidateQueueView {
  const shown = candidates.slice(0, CANDIDATE_PAGE_SIZE);
  const last = shown.at(-1);
  return {
    filter,
    rows: shown.map(candidateRow),
    nextHref:
      candidates.length > CANDIDATE_PAGE_SIZE && last !== undefined
        ? candidateQueueHref(pathname, { ...filter, after: last.candidateId })
        : null,
    firstHref:
      filter.after === null ? null : candidateQueueHref(pathname, { ...filter, after: null }),
  };
}
