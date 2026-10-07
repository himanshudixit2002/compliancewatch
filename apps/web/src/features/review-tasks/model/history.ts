import {
  DECISION_ACTIONS,
  type AuditEntry,
  type DecisionAction,
  type ReviewTask,
} from "@/entities/rule-version/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { ruleVersionStatusLabel } from "@/shared/ui/rule-version-status";
import {
  decisionLabel,
  personRef,
  taskHref,
  taskKindLabel,
  taskStatusLabel,
  type PersonRef,
} from "./queue";

/**
 * The history of a version under review: its decision audit as the rulebook keeps it (each
 * submission, return, approval, publication and edit, by whom, when and why, newest first), and
 * every review task the version (or the candidate, before drafting) has had, oldest first, each
 * opening its own workbench.
 */
const ACTION_LABELS: Readonly<Record<DecisionAction, MessageKey>> = {
  submitted: "workbench.action.submitted",
  returned: "workbench.action.returned",
  approved: "workbench.action.approved",
  published: "workbench.action.published",
  withdrawn: "workbench.action.withdrawn",
  superseded: "workbench.action.superseded",
  edited: "workbench.action.edited",
};

export function actionLabel(action: string): string {
  return (DECISION_ACTIONS as readonly string[]).includes(action)
    ? t(ACTION_LABELS[action as DecisionAction])
    : humanise(action);
}

export interface AuditRow {
  decisionId: string;
  action: string;
  /** "Draft to In review". */
  move: string;
  actor: PersonRef | null;
  note: string;
  at: string;
  /** The version whose publication caused it (a supersession), linked. */
  causedBy: { ruleVersionId: string; href: string } | null;
}

export interface TaskRow {
  taskId: string;
  href: string;
  current: boolean;
  kind: string;
  status: string;
  opened: string;
  claimed: { by: PersonRef; at: string | null } | null;
  decision: { label: string; by: PersonRef | null; at: string | null; note: string } | null;
}

export interface HistoryView {
  audit: AuditRow[];
  tasks: TaskRow[];
}

export function historyView(
  decisions: readonly AuditEntry[],
  tasks: readonly ReviewTask[],
  currentTaskId: string,
  sessionUserId: string,
): HistoryView {
  const versionPage = screenById("admin.rulebook.version");
  return {
    audit: [...decisions]
      .sort((a, b) => (a.decidedAt < b.decidedAt ? 1 : a.decidedAt > b.decidedAt ? -1 : 0))
      .map((entry) => ({
        decisionId: entry.decisionId,
        action: actionLabel(entry.action),
        move:
          entry.fromStatus === entry.toStatus
            ? ruleVersionStatusLabel(entry.toStatus)
            : t("workbench.history.move", {
                from: ruleVersionStatusLabel(entry.fromStatus),
                to: ruleVersionStatusLabel(entry.toStatus),
              }),
        actor: entry.actorId === null ? null : personRef(entry.actorId, sessionUserId),
        note: entry.note,
        at: formatDateTime(entry.decidedAt),
        causedBy:
          entry.causedByRuleVersionId === null
            ? null
            : {
                ruleVersionId: entry.causedByRuleVersionId,
                href: hrefFor(versionPage, { ruleVersionId: entry.causedByRuleVersionId }),
              },
      })),
    tasks: tasks.map((task) => ({
      taskId: task.taskId,
      href: taskHref(task.taskId),
      current: task.taskId === currentTaskId,
      kind: taskKindLabel(task.kind),
      status: taskStatusLabel(task.status),
      opened: formatDateTime(task.openedAt),
      claimed:
        task.claimedBy === null
          ? null
          : {
              by: personRef(task.claimedBy, sessionUserId),
              at: task.claimedAt === null ? null : formatDateTime(task.claimedAt),
            },
      decision:
        task.decision === null
          ? null
          : {
              label: decisionLabel(task.decision),
              by: task.decidedBy === null ? null : personRef(task.decidedBy, sessionUserId),
              at: task.decidedAt === null ? null : formatDateTime(task.decidedAt),
              note: task.note,
            },
    })),
  };
}
