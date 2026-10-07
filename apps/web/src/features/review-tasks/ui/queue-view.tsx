import type { Route } from "next";
import Link from "next/link";
import { Banner, EmptyState, PageHeader } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { FilterChips } from "@/shared/ui/filter-chips";
import { KeysetPager } from "@/shared/ui/keyset-pager";
import { ServiceError, type ServiceErrorLike } from "@/shared/ui/service-error";
import type { WriteAction } from "@/shared/ui/write-outcome";
import {
  emptyText,
  kindChips,
  queueHref,
  regulatorChips,
  statusChips,
  taskStatusLabel,
  type QueueFilter,
  type QueueView as QueueViewModel,
} from "../model/queue";
import type { StatsStrip as StatsStripModel } from "../model/stats";
import type { AccessView, WriteResult } from "./form-shared";
import { QueueList } from "./queue-list";
import { SeedTasksButton } from "./seed-tasks-button";
import { StatsStrip } from "./stats-strip";

export interface QueueViewProps {
  title: string;
  crumbs: readonly Crumb[];
  filter: QueueFilter;
  /** The page of tasks; null when the read failed. */
  view: QueueViewModel | null;
  error?: ServiceErrorLike;
  strip: StatsStripModel | null;
  stripError?: ServiceErrorLike;
  regulators: readonly string[];
  access: AccessView;
  claim: WriteAction<WriteResult> | null;
  openSeedTasks: WriteAction<WriteResult> | null;
  /** The planned part of the queue a reviewer or an admin is told about (D-039). */
  sampling: { title: string; waitingFor: string } | null;
}

/**
 * The review queue: the stats strip, opening the seed tasks, the filters (status, kind and
 * regulator, each a row of chips in the address) and a page of tasks in the rulebook's order with
 * their claim. The rows the signed-in analyst claimed are marked, since the rulebook has no
 * assignee filter. A later page whose read failed (a cursor the rulebook refuses, from another
 * filter or an older queue) leads back to the first page.
 */
export function QueueView({
  title,
  crumbs,
  filter,
  view,
  error,
  strip,
  stripError,
  regulators,
  access,
  claim,
  openSeedTasks,
  sampling,
}: QueueViewProps) {
  const empty = emptyText(filter);
  return (
    <div data-slot="review-queue" className="flex max-w-6xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("reviewQueue.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <StatsStrip strip={strip} {...(stripError === undefined ? {} : { error: stripError })} />
      {access.allowed ? null : (
        <Banner tone="warning" title={access.title} data-slot="review-access">
          {access.detail ?? t("reviewQueue.accessDetail")}
        </Banner>
      )}
      {openSeedTasks === null ? null : <SeedTasksButton action={openSeedTasks} />}
      <div className="flex flex-col gap-3" data-slot="queue-filters">
        <FilterChips label={t("reviewQueue.chips.status")} chips={statusChips(filter)} />
        <FilterChips label={t("reviewQueue.chips.kind")} chips={kindChips(filter)} />
        <FilterChips
          label={t("reviewQueue.chips.regulator")}
          chips={regulatorChips(filter, regulators)}
        />
      </div>
      {error !== undefined ? <ServiceError error={error} /> : null}
      {error !== undefined && filter.cursor !== null ? (
        <p className="text-sm" data-slot="queue-first-page">
          <Link
            href={queueHref({ ...filter, cursor: null }) as Route}
            className="text-primary underline-offset-2 hover:underline"
          >
            {t("reviewQueue.backToFirst")}
          </Link>
        </p>
      ) : null}
      {view === null ? null : view.rows.length === 0 ? (
        <>
          <EmptyState title={empty.title} body={empty.body} />
          <KeysetPager
            nextHref={null}
            firstHref={view.firstHref}
            label={t("reviewQueue.pager")}
            nextLabel={t("reviewQueue.nextPage")}
            firstLabel={t("reviewQueue.firstPage")}
          />
        </>
      ) : (
        <>
          <QueueList
            rows={view.rows}
            caption={t("reviewQueue.caption", {
              count: view.rows.length,
              status: taskStatusLabel(filter.status),
            })}
            claim={claim}
          />
          <KeysetPager
            nextHref={view.nextHref}
            firstHref={view.firstHref}
            label={t("reviewQueue.pager")}
            nextLabel={t("reviewQueue.nextPage")}
            firstLabel={t("reviewQueue.firstPage")}
          />
        </>
      )}
      {sampling === null ? null : (
        <p className="max-w-prose text-sm text-fg-muted" data-slot="review-sampling">
          {t("reviewQueue.sampling", { title: sampling.title, waiting: sampling.waitingFor })}
        </p>
      )}
    </div>
  );
}
