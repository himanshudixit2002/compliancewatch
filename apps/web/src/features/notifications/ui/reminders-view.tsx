import { EmptyState, PageHeader } from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { SectionNav } from "@/shared/ui/section-nav";
import { deliveryLabel, stateOptions } from "../model/notifications";
import type { RemindersView as RemindersViewModel } from "../model/history";
import { HistoryPager } from "./history-pager";
import { NotificationsTable } from "./notifications-table";
import { StateFilter } from "./state-filter";

export interface RemindersViewProps {
  title: string;
  view: RemindersViewModel;
  /** The business's breadcrumbs and pages, as every business page shows them. */
  header: { crumbs: readonly Crumb[]; tabs: readonly NavLink[] };
  /** The page itself, without a query: the filter's action. */
  pageHref: string;
}

/**
 * The notifications sent for a business, newest first, with the delivery state to filter by:
 * what the notification service recorded of each (template, channel, masked address, state,
 * attempts, times), never a message text it does not keep. An empty history says why it is
 * empty: nothing queued yet, or nothing in the state chosen.
 */
export function RemindersView({ title, view, header, pageHref }: RemindersViewProps) {
  const { rows, filter } = view;
  return (
    <div data-slot="reminders" className="flex max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-4">
        <PageHeader
          title={title}
          description={t("business.pageIntro", {
            name: view.business.name,
            pan: view.business.pan,
          })}
          breadcrumbs={<Breadcrumbs crumbs={header.crumbs} />}
        />
        <SectionNav items={header.tabs} label={t("business.tabs")} />
      </div>
      <p className="max-w-prose text-sm text-fg-muted">{t("notificationLog.intro")}</p>
      <StateFilter action={pageHref} state={filter.state} options={stateOptions()} />
      {rows.length === 0 ? (
        filter.state === undefined ? (
          <EmptyState
            title={t("notificationLog.emptyTitle")}
            body={t("notificationLog.emptyBody")}
          />
        ) : (
          <EmptyState
            title={t("notificationLog.emptyStateTitle")}
            body={t("notificationLog.emptyStateBody", { state: deliveryLabel(filter.state) })}
          />
        )
      ) : (
        <NotificationsTable rows={rows} />
      )}
      <HistoryPager nextHref={view.nextHref} firstHref={view.firstHref} />
    </div>
  );
}
