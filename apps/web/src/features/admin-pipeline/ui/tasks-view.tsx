import type { Route } from "next";
import Link from "next/link";
import {
  Banner,
  EmptyState,
  JsonView,
  KeyValue,
  PageHeader,
  StatusChip,
  type KeyValueItem,
} from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { FilterChips } from "@/shared/ui/filter-chips";
import { KeysetPager } from "@/shared/ui/keyset-pager";
import { DocumentStatusChip } from "@/shared/ui/pipeline";
import { RefreshButton } from "@/shared/ui/refresh-button";
import type { WriteAction } from "@/shared/ui/write-outcome";
import {
  kindChips,
  statusChips,
  taskKindLabel,
  taskStatusLabel,
  type TaskCard,
  type TaskFilter,
  type TasksView as TasksViewModel,
} from "../model/tasks";
import type { AccessView, WriteResult } from "./pipeline-shared";
import { TaskPanel } from "./task-panel";

export interface TaskActions {
  resolve: WriteAction<WriteResult>;
  dismiss: WriteAction<WriteResult>;
}

export interface TasksViewProps {
  title: string;
  crumbs: readonly Crumb[];
  view: TasksViewModel;
  access: AccessView;
  /** The resolve and dismiss actions bound to an open task; null when the session may only read. */
  actionsFor: ((card: TaskCard) => TaskActions) | null;
}

function emptyText(filter: TaskFilter): { title: string; body: string } {
  if (filter.cursor !== null) {
    return { title: t("pipelineTasks.empty.laterTitle"), body: t("pipelineTasks.empty.laterBody") };
  }
  if (filter.status === "open" && filter.kind === null) {
    return { title: t("pipelineTasks.empty.openTitle"), body: t("pipelineTasks.empty.openBody") };
  }
  const kind = filter.kind === null ? null : taskKindLabel(filter.kind).toLowerCase();
  const status = filter.status === null ? null : taskStatusLabel(filter.status).toLowerCase();
  const title =
    kind === null
      ? status === null
        ? t("pipelineTasks.empty.noneTitle")
        : t("pipelineTasks.empty.statusTitle", { status })
      : status === null
        ? t("pipelineTasks.empty.kindOnlyTitle", { kind })
        : t("pipelineTasks.empty.kindTitle", { status, kind });
  return { title, body: t("pipelineTasks.empty.filteredBody") };
}

function TaskArticle({ card, actions }: { card: TaskCard; actions: TaskActions | null }) {
  const headingId = `task-${card.taskId}`;
  const facts: KeyValueItem[] = [
    {
      key: "source",
      label: t("pipelineTasks.facts.source"),
      value: (
        <Link
          href={card.sourceHref as Route}
          className="font-mono text-primary underline-offset-2 hover:underline"
        >
          {card.sourceKey}
        </Link>
      ),
    },
    {
      key: "opened",
      label: t("pipelineTasks.facts.opened"),
      value: <time dateTime={card.openedIso}>{card.opened}</time>,
    },
    {
      key: "why",
      label: t("pipelineTasks.facts.why"),
      value: card.reason === "" ? t("common.none") : card.reason,
    },
    {
      key: "document",
      label: t("pipelineTasks.facts.documentStatus"),
      value: <DocumentStatusChip status={card.document.status} />,
    },
    ...(card.claimedBy === null
      ? []
      : [
          {
            key: "claimed",
            label: t("pipelineTasks.facts.claimedBy"),
            value: <code className="font-mono text-xs">{card.claimedBy}</code>,
          },
        ]),
    ...(card.closed === null
      ? []
      : [
          {
            key: "closed",
            label:
              card.status === "dismissed"
                ? t("pipelineTasks.facts.dismissedBy")
                : t("pipelineTasks.facts.resolvedBy"),
            value: (
              <span className="flex flex-col gap-0.5">
                {card.closed.by === null ? (
                  t("pipelineTasks.facts.closedByPipeline")
                ) : (
                  <code className="font-mono text-xs">{card.closed.by}</code>
                )}
                {card.closed.at === null || card.closed.atIso === null ? null : (
                  <time dateTime={card.closed.atIso} className="text-xs text-fg-muted">
                    {card.closed.at}
                  </time>
                )}
              </span>
            ),
          },
          {
            key: "note",
            label: t("pipelineTasks.facts.note"),
            value: card.closed.note === "" ? t("common.none") : card.closed.note,
          },
        ]),
  ];
  return (
    <article
      aria-labelledby={headingId}
      data-task={card.taskId}
      data-kind={card.kind}
      data-status={card.status}
      className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-4"
    >
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <StatusChip status={card.status} tone={card.statusTone} label={card.statusLabel} />
          <span className="text-sm font-medium text-fg-muted">{card.kindLabel}</span>
        </div>
        <h2 id={headingId} className="text-lg font-semibold text-fg">
          <Link
            href={card.document.href as Route}
            className="text-primary underline-offset-2 hover:underline"
          >
            {card.document.title}
          </Link>
        </h2>
        <p className="text-sm">
          <a
            href={card.document.rawHref}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline-offset-2 hover:underline"
          >
            {t("pipelineTasks.openFile")}
          </a>
        </p>
      </div>
      <KeyValue items={facts} />
      {card.resolution === null ? null : (
        <JsonView value={card.resolution} label={t("pipelineTasks.facts.resolution")} />
      )}
      {card.status === "open" && actions !== null ? (
        <TaskPanel
          kind={card.kind}
          resolve={actions.resolve}
          dismiss={actions.dismiss}
          documentTitle={card.document.title}
        />
      ) : null}
    </article>
  );
}

/**
 * The pipeline's tasks: open manual parses (a document no parser reads, waiting for an analyst to
 * type it in) and open triages (a document whose text names another type than its source
 * publishes, waiting for a person's decision) first, oldest first; resolved and dismissed ones by
 * the chips. Each task names its document (opening its page and its stored file), why it opened
 * and, once closed, who closed it, when and why; an admin resolves or dismisses an open one.
 */
export function TasksView({ title, crumbs, view, access, actionsFor }: TasksViewProps) {
  const empty = emptyText(view.filter);
  return (
    <div data-slot="pipeline-tasks" className="flex max-w-5xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("pipelineTasks.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
        actions={<RefreshButton />}
      />
      <FilterChips label={t("pipelineTasks.statusChips")} chips={statusChips(view.filter)} />
      <FilterChips label={t("pipelineTasks.kindChips")} chips={kindChips(view.filter)} />
      {access.allowed ? null : (
        <Banner tone="neutral" title={access.title} data-slot="tasks-read-only">
          {access.detail ?? t("pipelineTasks.readOnly")}
        </Banner>
      )}
      {view.cards.length === 0 ? (
        <EmptyState title={empty.title} body={empty.body} />
      ) : (
        <div className="flex flex-col gap-4" data-slot="task-list">
          {view.cards.map((card) => (
            <TaskArticle
              key={card.taskId}
              card={card}
              actions={actionsFor === null || !access.allowed ? null : actionsFor(card)}
            />
          ))}
        </div>
      )}
      <KeysetPager
        nextHref={view.nextHref}
        firstHref={view.firstHref}
        label={t("pipelineTasks.pager")}
        nextLabel={t("pipelineTasks.next")}
        firstLabel={t("pipelineTasks.first")}
      />
    </div>
  );
}
