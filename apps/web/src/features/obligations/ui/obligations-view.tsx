import { EmptyState, PageHeader, type SelectOption } from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { NotLegalAdvice } from "@/shared/ui/not-legal-advice";
import { SectionNav } from "@/shared/ui/section-nav";
import { MAX_WINDOW_DAYS, windowText } from "../model/list";
import { ALL_STATUSES } from "../model/obligations";
import type { ObligationListView } from "../queries";
import { ListPager } from "./list-pager";
import { ObligationFilters } from "./obligation-filters";
import { ObligationsTable } from "./obligations-table";

export interface ObligationsViewProps {
  title: string;
  view: ObligationListView;
  header: { crumbs: readonly Crumb[]; tabs: readonly NavLink[] };
  /** The list itself, without a query. */
  pageHref: string;
  statusOptions: readonly SelectOption[];
  /** Whether the business has more than one node, so a row names the one it is kept for. */
  severalNodes: boolean;
}

/**
 * A business's obligations by due date, a page at a time, with the status and the due window to
 * filter by. An empty list says why: nothing worked out yet, or nothing matching the filter. A
 * window the service would refuse is shown on its field and nothing is listed for it.
 */
export function ObligationsView({
  title,
  view,
  header,
  pageHref,
  statusOptions,
  severalNodes,
}: ObligationsViewProps) {
  const { read, rows } = view;
  const filtered =
    read.filter.status !== ALL_STATUSES || read.filter.from !== null || read.filter.to !== null;
  const window = windowText(read.filter);
  return (
    <div data-slot="obligations" className="flex max-w-5xl flex-col gap-6">
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
      <p className="max-w-prose text-sm text-fg-muted">{t("obligations.intro")}</p>
      <ObligationFilters
        action={pageHref}
        status={read.filter.status}
        options={statusOptions}
        from={read.typed.from}
        to={read.typed.to}
        errors={read.errors}
        maxDays={MAX_WINDOW_DAYS}
      />
      {!view.asked ? (
        <EmptyState
          title={t("obligations.window.refusedTitle")}
          body={t("obligations.window.refusedBody", { max: MAX_WINDOW_DAYS })}
        />
      ) : rows.length === 0 ? (
        filtered ? (
          <EmptyState
            title={t("obligations.noMatch.title")}
            body={
              window === null
                ? t("obligations.noMatch.body")
                : t("obligations.noMatch.window", { window })
            }
          />
        ) : read.filter.after !== null ? (
          <EmptyState
            title={t("obligations.pager.endTitle")}
            body={t("obligations.pager.endBody")}
          />
        ) : (
          <EmptyState title={t("obligations.empty.title")} body={t("obligations.empty.body")} />
        )
      ) : (
        <>
          {window === null ? null : <p className="text-sm text-fg-muted">{window}</p>}
          <ObligationsTable rows={rows} showNode={severalNodes} />
        </>
      )}
      <ListPager
        nextHref={view.nextHref}
        firstHref={view.firstHref}
        label={t("obligations.pager.label")}
      />
      <NotLegalAdvice />
    </div>
  );
}
