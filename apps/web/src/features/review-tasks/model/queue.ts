import {
  REVIEW_TASK_KINDS,
  REVIEW_TASK_STATUSES,
  type QueuedTask,
  type ReviewDecision,
  type ReviewTaskKind,
  type ReviewTaskStatus,
} from "@/entities/rule-version/types";
import { toAwaitedItem } from "@/entities/screen/mappers";
import type { Role } from "@/shared/config/roles";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { withQuery } from "@/shared/lib/url";
import type { FilterChip } from "@/shared/ui/filter-chips";
import type { PersonRef } from "../ui/form-shared";

/**
 * The review queue: the rulebook's review tasks in its own order (by regulator, higher priority
 * first, then the oldest), a page at a time with the cursor the rulebook hands out. The query
 * string holds the filters and where the page starts; none of them is personal data.
 *
 *   status     open (the default), claimed, decided, or all
 *   kind       seed or candidate; every kind when absent
 *   regulator  one regulator's tasks (the rulebook compares it in lower case)
 *   cursor     the rulebook's next_cursor of the page before, opaque
 *
 * The rulebook has no assignee filter, so the tasks the signed-in analyst claimed are marked on
 * their rows rather than offered as a filter.
 */
export const QUEUE_PARAMS = {
  status: "status",
  kind: "kind",
  regulator: "regulator",
  cursor: "cursor",
} as const;

/** Rows a page shows. */
export const QUEUE_PAGE_SIZE = 25;
/** The rulebook's limits on the regulator filter and the cursor. */
export const REGULATOR_MAX = 40;
export const CURSOR_MAX = 512;

export type StatusChoice = ReviewTaskStatus | "all";

export interface QueueFilter {
  status: StatusChoice;
  kind: ReviewTaskKind | null;
  /** Lower case, as the rulebook compares it. */
  regulator: string | null;
  cursor: string | null;
}

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(query: Query, key: string): string {
  const value = query[key];
  return ((Array.isArray(value) ? value[0] : value) ?? "").trim();
}

export function isTaskStatus(value: string): value is ReviewTaskStatus {
  return (REVIEW_TASK_STATUSES as readonly string[]).includes(value);
}

export function isTaskKind(value: string): value is ReviewTaskKind {
  return (REVIEW_TASK_KINDS as readonly string[]).includes(value);
}

/** The filter the address asks for; a value out of shape is read as no filter. */
export function readQueueFilter(query: Query): QueueFilter {
  const status = first(query, QUEUE_PARAMS.status);
  const kind = first(query, QUEUE_PARAMS.kind);
  const regulator = first(query, QUEUE_PARAMS.regulator).toLowerCase();
  const cursor = first(query, QUEUE_PARAMS.cursor);
  return {
    status: status === "all" ? "all" : isTaskStatus(status) ? status : "open",
    kind: isTaskKind(kind) ? kind : null,
    regulator: regulator === "" || regulator.length > REGULATOR_MAX ? null : regulator,
    cursor: cursor === "" || cursor.length > CURSOR_MAX ? null : cursor,
  };
}

export function queueHref(filter: QueueFilter): string {
  return withQuery(hrefFor(screenById("admin.review")), {
    [QUEUE_PARAMS.status]: filter.status === "open" ? undefined : filter.status,
    [QUEUE_PARAMS.kind]: filter.kind ?? undefined,
    [QUEUE_PARAMS.regulator]: filter.regulator ?? undefined,
    [QUEUE_PARAMS.cursor]: filter.cursor ?? undefined,
  });
}

const STATUS_LABELS: Readonly<Record<StatusChoice, MessageKey>> = {
  open: "reviewQueue.status.open",
  claimed: "reviewQueue.status.claimed",
  decided: "reviewQueue.status.decided",
  all: "reviewQueue.status.all",
};

export function taskStatusLabel(status: string): string {
  return isTaskStatus(status) || status === "all"
    ? t(STATUS_LABELS[status as StatusChoice])
    : humanise(status);
}

const KIND_LABELS: Readonly<Record<ReviewTaskKind, MessageKey>> = {
  seed: "reviewQueue.kind.seed",
  candidate: "reviewQueue.kind.candidate",
};

export function taskKindLabel(kind: string): string {
  return isTaskKind(kind) ? t(KIND_LABELS[kind]) : humanise(kind);
}

const DECISION_LABELS: Readonly<Record<ReviewDecision, MessageKey>> = {
  approve: "reviewQueue.decision.approve",
  return: "reviewQueue.decision.return",
  reject: "reviewQueue.decision.reject",
};

export function decisionLabel(decision: string): string {
  return decision in DECISION_LABELS
    ? t(DECISION_LABELS[decision as ReviewDecision])
    : humanise(decision);
}

/** One chip per status, each keeping the kind and regulator and starting from the first page. */
export function statusChips(filter: QueueFilter): FilterChip[] {
  return (["open", "claimed", "decided", "all"] as const).map((status) => ({
    key: status,
    label: t(STATUS_LABELS[status]),
    href: queueHref({ ...filter, status, cursor: null }),
    current: status === filter.status,
  }));
}

export function kindChips(filter: QueueFilter): FilterChip[] {
  return [
    {
      key: "any",
      label: t("reviewQueue.kind.any"),
      href: queueHref({ ...filter, kind: null, cursor: null }),
      current: filter.kind === null,
    },
    ...REVIEW_TASK_KINDS.map((kind) => ({
      key: kind,
      label: t(KIND_LABELS[kind]),
      href: queueHref({ ...filter, kind, cursor: null }),
      current: kind === filter.kind,
    })),
  ];
}

/**
 * One chip per regulator the stats count (every regulator with a task), plus the one the address
 * names when the stats do not hold it, so the current filter always shows as a chip.
 */
export function regulatorChips(filter: QueueFilter, regulators: readonly string[]): FilterChip[] {
  const known = [...new Set(regulators.map((regulator) => regulator.toLowerCase()))];
  if (filter.regulator !== null && !known.includes(filter.regulator)) known.push(filter.regulator);
  return [
    {
      key: "any",
      label: t("reviewQueue.regulator.any"),
      href: queueHref({ ...filter, regulator: null, cursor: null }),
      current: filter.regulator === null,
    },
    ...known.sort().map((regulator) => ({
      key: regulator,
      label: regulator,
      href: queueHref({ ...filter, regulator, cursor: null }),
      current: regulator === filter.regulator,
    })),
  ];
}

export type { PersonRef };

export function personRef(userId: string, sessionUserId: string): PersonRef {
  return { userId, you: userId === sessionUserId };
}

export interface QueueRow {
  taskId: string;
  href: string;
  kind: ReviewTaskKind;
  kindLabel: string;
  title: string;
  /** "example_rule v2", or before drafting the key the candidate suggests (null: none). */
  ruleLabel: string | null;
  /** The key is only suggested: the candidate is not drafted yet. */
  suggested: boolean;
  versionStatus: string | null;
  /** "1 of 2 approvals". */
  approvals: string;
  highImpact: boolean;
  /** A candidate task's extraction, in words. */
  candidate: {
    outcome: string;
    unparseable: boolean;
    confidence: string;
    issues: string;
    needsReview: boolean;
  } | null;
  status: ReviewTaskStatus;
  statusLabel: string;
  claimedBy: PersonRef | null;
  claimedAt: string | null;
  /** The signed-in analyst claimed it. */
  mine: boolean;
  /** "Approved", with who and when. */
  decision: { label: string; by: PersonRef | null; at: string | null; note: string } | null;
  /** Open, so anyone may claim it. */
  claimable: boolean;
}

/** A share in [0, 1] as a whole percentage: 0.875 reads "88%". */
export function percent(share: number): string {
  return `${Math.round(Math.min(Math.max(share, 0), 1) * 100)}%`;
}

export function approvalsText(approvals: number, required: number): string {
  return t("reviewQueue.approvals", { count: approvals, required });
}

export function taskHref(taskId: string): string {
  return hrefFor(screenById("admin.review.task"), { taskId });
}

export function queueRow(task: QueuedTask, sessionUserId: string): QueueRow {
  const candidate = task.candidate;
  const suggested = task.version === null;
  return {
    taskId: task.taskId,
    href: taskHref(task.taskId),
    kind: task.kind,
    kindLabel: taskKindLabel(task.kind),
    title: task.title,
    ruleLabel:
      task.ruleKey === null
        ? null
        : task.version === null
          ? task.ruleKey
          : t("reviewQueue.ruleVersion", { rule: task.ruleKey, version: task.version }),
    suggested,
    versionStatus: task.versionStatus,
    approvals: approvalsText(task.approvals, task.requiredApprovals),
    highImpact: task.highImpact,
    candidate:
      candidate === null
        ? null
        : {
            outcome:
              candidate.outcome === "unparseable"
                ? t("reviewQueue.candidate.unparseable")
                : t("reviewQueue.candidate.extracted"),
            unparseable: candidate.outcome === "unparseable",
            confidence: t("reviewQueue.candidate.confidence", {
              score: percent(candidate.confidence),
            }),
            issues: t("reviewQueue.candidate.issues", { count: candidate.issueCount }),
            needsReview: candidate.needsReview,
          },
    status: task.status,
    statusLabel: taskStatusLabel(task.status),
    claimedBy: task.claimedBy === null ? null : personRef(task.claimedBy, sessionUserId),
    claimedAt: task.claimedAt === null ? null : formatDateTime(task.claimedAt),
    mine: task.claimedBy !== null && task.claimedBy === sessionUserId,
    decision:
      task.decision === null
        ? null
        : {
            label: decisionLabel(task.decision),
            by: task.decidedBy === null ? null : personRef(task.decidedBy, sessionUserId),
            at: task.decidedAt === null ? null : formatDateTime(task.decidedAt),
            note: task.note,
          },
    claimable: task.status === "open",
  };
}

export interface QueueView {
  filter: QueueFilter;
  rows: QueueRow[];
  nextHref: string | null;
  firstHref: string | null;
}

export function queueView(
  filter: QueueFilter,
  tasks: readonly QueuedTask[],
  nextCursor: string | null,
  sessionUserId: string,
): QueueView {
  return {
    filter,
    rows: tasks.map((task) => queueRow(task, sessionUserId)),
    nextHref: nextCursor === null ? null : queueHref({ ...filter, cursor: nextCursor }),
    firstHref: filter.cursor === null ? null : queueHref({ ...filter, cursor: null }),
  };
}

/** Why a page holds no task, in its own words. */
export function emptyText(filter: QueueFilter): { title: string; body: string } {
  if (filter.cursor !== null) {
    return { title: t("reviewQueue.empty.laterTitle"), body: t("reviewQueue.empty.laterBody") };
  }
  if (filter.kind !== null || filter.regulator !== null) {
    return {
      title: t("reviewQueue.empty.filteredTitle"),
      body: t("reviewQueue.empty.filteredBody"),
    };
  }
  switch (filter.status) {
    case "open":
      return { title: t("reviewQueue.empty.openTitle"), body: t("reviewQueue.empty.openBody") };
    case "claimed":
      return {
        title: t("reviewQueue.empty.claimedTitle"),
        body: t("reviewQueue.empty.claimedBody"),
      };
    case "decided":
      return {
        title: t("reviewQueue.empty.decidedTitle"),
        body: t("reviewQueue.empty.decidedBody"),
      };
    case "all":
      return { title: t("reviewQueue.empty.allTitle"), body: t("reviewQueue.empty.allBody") };
  }
}

/**
 * What the queue says about review sampling, the planned part of it (D-039): its registry entry's
 * title and the route it waits for, for the roles the entry names; null for anyone else.
 */
export function samplingNote(roles: readonly Role[]): { title: string; waitingFor: string } | null {
  const entry = screenById("admin.review-sampling");
  if (entry.status === "live" || entry.roles === "public") return null;
  const allowed = entry.roles;
  if (!roles.some((role) => allowed.includes(role))) return null;
  return {
    title: entry.title,
    waitingFor: entry.awaits
      .map(toAwaitedItem)
      .map((item) => `${item.method} ${item.path} (${item.owner})`)
      .join("; "),
  };
}
