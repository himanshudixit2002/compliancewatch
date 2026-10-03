"use client";

import type { Route } from "next";
import Link from "next/link";
import { Badge, Button, Card, KeyValue, PageHeader } from "@compliancewatch/ui";
import type { KeyValueItem } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  reviewPriorityLabel,
  reviewTypeLabel,
  type ReviewTask,
} from "@/features/review-queue";
import { reviewTaskStatusLabel, reviewTaskStatusTone } from "../model/review-task";

function priorityTone(priority: string): "success" | "info" | "warning" | "danger" {
  switch (priority) {
    case "high": return "danger";
    case "medium": return "warning";
    default: return "info";
  }
}

export interface ReviewTaskDetailProps {
  task: ReviewTask;
  /** Triggered when the reviewer approves the task. */
  onApprove?: () => void;
  /** Triggered when the reviewer rejects the task. */
  onReject?: () => void;
  /** Triggered when the reviewer assigns the task to themselves or someone else. */
  onAssign?: () => void;
  /** Where the back-to-queue link points; defaults to the admin review queue. */
  backHref?: Route;
}

function actionButtonVariant(
  tone: "primary" | "secondary" | "danger" | undefined,
): { variant: "default" | "outline" | "destructive" } {
  if (tone === "danger") return { variant: "destructive" };
  if (tone === "secondary") return { variant: "outline" };
  return { variant: "default" };
}

/**
 * The reviewer workbench: the task's title and status, a row of facts (priority, status,
 * assignee, due date), the structured detail panel and the actions the current user may take.
 */
export function ReviewTaskDetailComponent({
  task,
  onApprove,
  onReject,
  onAssign,
  backHref,
}: ReviewTaskDetailProps) {
  const canAct = task.status === "pending";

  const items: KeyValueItem[] = [
    { key: "id", label: t("reviewTask.id"), value: task.id, copy: task.id },
    { key: "type", label: t("reviewTask.type"), value: reviewTypeLabel(task.type) },
    {
      key: "createdAt",
      label: t("reviewTask.createdAt"),
      value: formatDateTime(task.createdAt),
    },
    {
      key: "description",
      label: t("reviewTask.description"),
      value: task.description || "—",
    },
  ];

  return (
    <div data-slot="review-task-detail" className="flex flex-col gap-6">
      <div>
        <Link
          href={backHref ?? ("/admin/review" as Route)}
          className="text-sm text-fg-muted underline-offset-2 hover:underline"
        >
          {t("reviewTask.back")}
        </Link>
      </div>
      <PageHeader
        title={task.title || t("reviewTask.untitled")}
        description={t("reviewTask.detailDescription")}
      >
        <Badge tone={reviewTaskStatusTone(task.status)}>
          {reviewTaskStatusLabel(task.status)}
        </Badge>
      </PageHeader>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={t("reviewTask.priority")}
          value={reviewPriorityLabel(task.priority)}
          tone={priorityTone(task.priority)}
        />
        <StatCard
          label={t("reviewTask.status")}
          value={reviewTaskStatusLabel(task.status)}
          tone={reviewTaskStatusTone(task.status)}
        />
        <StatCard
          label={t("reviewTask.assignee")}
          value={task.assignee || t("reviewTask.unassigned")}
          tone={task.assignee ? "info" : "neutral"}
        />
        <StatCard
          label={t("reviewTask.dueAt")}
          value={task.dueAt ? formatDateTime(task.dueAt) : t("reviewTask.noDueDate")}
          tone="neutral"
        />
      </div>

      <Card className="gap-3 p-4">
        <h2 className="text-base font-semibold text-fg">{t("reviewTask.details")}</h2>
        <KeyValue items={items} />
      </Card>

      <div className="flex flex-wrap gap-2">
        {canAct ? (
          <Button onClick={onApprove}>{t("reviewTask.action.approve")}</Button>
        ) : null}
        {canAct ? (
          <Button
            {...actionButtonVariant("danger")}
            onClick={onReject}
          >
            {t("reviewTask.action.reject")}
          </Button>
        ) : null}
        {canAct ? (
          <Button
            {...actionButtonVariant("secondary")}
            onClick={onAssign}
          >
            {t("reviewTask.action.assign")}
          </Button>
        ) : null}
      </div>
    </div>
  );
}