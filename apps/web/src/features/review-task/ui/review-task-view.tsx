import type { Route } from "next";
import Link from "next/link";
import {
  Button,
  Field,
  KeyValue,
  PageHeader,
  REASON_MIN_LENGTH,
  Textarea,
  type KeyValueItem,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { humanise } from "@/shared/lib/humanise";
import { StatCard } from "@/shared/ui/stat-card";
import {
  REVIEW_DECISION_FIELDS,
  isPastDue,
  reviewTaskPriorityLabel,
  reviewTaskPriorityTone,
  reviewTaskStatusLabel,
  reviewTaskStatusTone,
  reviewTaskTypeLabel,
  type ReviewDecision,
  type ReviewTask,
} from "../model/review-task";

type FormAction = (formData: FormData) => Promise<void>;

export interface ReviewTaskViewProps {
  task: ReviewTask;
  /** The review queue, for the back link. */
  backHref: Route;
  /**
   * Records the decision read from REVIEW_DECISION_FIELDS: approve, or reject with a reason (a
   * server action). No route takes a decision yet, so the decision forms show only when the page
   * passes one, and only while the task is pending.
   */
  decideAction?: FormAction;
  /** Assigns the task to the signed-in reviewer (a server action); offered while it is pending
   *  and unassigned. */
  claimAction?: FormAction;
  /** Now, for the due time; tests pass a fixed instant. */
  now?: Date;
}

function Identifier({ value }: { value: string }) {
  return <code className="font-mono text-xs">{value}</code>;
}

function details(task: ReviewTask): KeyValueItem[] {
  const { nodeId, financialYear, reason, documentId } = task.metadata;
  const items: KeyValueItem[] = [
    { key: "id", label: t("reviewTask.id"), value: <Identifier value={task.id} />, copy: task.id },
    { key: "type", label: t("reviewTask.type"), value: reviewTaskTypeLabel(task.type) },
    { key: "created", label: t("reviewTask.createdAt"), value: formatDateTime(task.createdAt) },
  ];
  if (nodeId !== undefined) {
    items.push({
      key: "node",
      label: t("reviewTask.field.node"),
      value: <Identifier value={nodeId} />,
      copy: nodeId,
    });
  }
  if (financialYear !== undefined) {
    items.push({
      key: "financial-year",
      label: t("reviewTask.field.financialYear"),
      value: financialYear,
    });
  }
  if (reason !== undefined) {
    items.push({ key: "reason", label: t("reviewTask.field.reason"), value: humanise(reason) });
  }
  if (documentId !== undefined) {
    items.push({
      key: "document",
      label: t("reviewTask.field.document"),
      value: <Identifier value={documentId} />,
      copy: documentId,
    });
  }
  return items;
}

function DecisionField({ decision }: { decision: ReviewDecision }) {
  return <input type="hidden" name={REVIEW_DECISION_FIELDS.decision} value={decision} />;
}

function DecisionForms({ action }: { action: FormAction }) {
  return (
    <section aria-labelledby="review-task-decision" className="flex flex-col gap-4">
      <h2 id="review-task-decision" className="text-lg font-semibold text-fg">
        {t("reviewTask.decision.title")}
      </h2>
      <form action={action} data-decision="approve">
        <DecisionField decision="approve" />
        <Button type="submit">{t("reviewTask.action.approve")}</Button>
      </form>
      <form action={action} data-decision="reject" className="flex max-w-xl flex-col gap-3">
        <DecisionField decision="reject" />
        <Field
          id="review-task-reason"
          label={t("reviewTask.decision.reason")}
          description={t("reviewTask.decision.reasonHelp", { min: REASON_MIN_LENGTH })}
          required
        >
          <Textarea name={REVIEW_DECISION_FIELDS.reason} required minLength={REASON_MIN_LENGTH} />
        </Field>
        <Button type="submit" variant="danger" className="w-fit">
          {t("reviewTask.action.reject")}
        </Button>
      </form>
    </section>
  );
}

/**
 * The reviewer workbench for one task: its status, priority, assignee and due time, the details
 * and metadata stored with it, and, while it is pending, the decision. Assigning and deciding
 * show only when the page passes the server actions for them.
 */
export function ReviewTaskView({
  task,
  backHref,
  decideAction,
  claimAction,
  now = new Date(),
}: ReviewTaskViewProps) {
  const pending = task.status === "pending";
  const pastDue = isPastDue(task, now);
  return (
    <div data-slot="review-task" className="flex flex-col gap-6">
      <Link
        href={backHref}
        className="w-fit text-sm text-fg-muted underline-offset-2 hover:underline"
      >
        {t("reviewTask.back")}
      </Link>
      <PageHeader
        title={task.title}
        description={task.description}
        actions={
          claimAction !== undefined && pending && task.assignee === null ? (
            <form action={claimAction} data-slot="claim">
              <Button type="submit" variant="secondary">
                {t("reviewTask.action.assign")}
              </Button>
            </form>
          ) : undefined
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={t("reviewTask.status")}
          value={reviewTaskStatusLabel(task.status)}
          tone={reviewTaskStatusTone(task.status)}
        />
        <StatCard
          label={t("reviewTask.priority")}
          value={reviewTaskPriorityLabel(task.priority)}
          tone={reviewTaskPriorityTone(task.priority)}
        />
        <StatCard
          label={t("reviewTask.assignee")}
          value={task.assignee ?? t("reviewTask.unassigned")}
          tone={task.assignee === null ? "neutral" : "info"}
        />
        <StatCard
          label={t("reviewTask.dueAt")}
          value={task.dueAt === null ? t("reviewTask.noDueDate") : formatDateTime(task.dueAt)}
          tone={pastDue ? "danger" : "neutral"}
          hint={pastDue ? t("reviewTask.pastDue") : undefined}
        />
      </div>
      <section aria-labelledby="review-task-details" className="flex flex-col gap-3">
        <h2 id="review-task-details" className="text-lg font-semibold text-fg">
          {t("reviewTask.details")}
        </h2>
        <KeyValue items={details(task)} />
      </section>
      {pending && decideAction !== undefined ? <DecisionForms action={decideAction} /> : null}
    </div>
  );
}
