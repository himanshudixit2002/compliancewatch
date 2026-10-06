import type { Route } from "next";
import Link from "next/link";
import { EmptyState, PageHeader } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import type { FanOutListView } from "../queries";
import { FanOutsTable } from "./fan-outs-table";
import { HoldPanel } from "./hold-panel";
import type { ControlAction } from "./use-control";

export interface FanOutsViewProps {
  title: string;
  crumbs: readonly Crumb[];
  view: FanOutListView;
  holdAction: ControlAction;
}

/**
 * Every rule version's fan-out, newest first, under the global hold: the hold as a danger banner
 * while it is set (with its toggle for an admin), then the runs a page at a time. Before any
 * version is published there is no run, and the page says so.
 */
export function FanOutsView({ title, crumbs, view, holdAction }: FanOutsViewProps) {
  return (
    <div data-slot="fan-outs" className="flex max-w-5xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("fanOuts.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <HoldPanel hold={view.hold} canControl={view.canControl} action={holdAction} />
      {view.rows.length === 0 ? (
        view.firstHref === null ? (
          <EmptyState title={t("fanOuts.empty.title")} body={t("fanOuts.empty.body")} />
        ) : (
          <EmptyState title={t("fanOuts.end.title")} body={t("fanOuts.end.body")} />
        )
      ) : (
        <FanOutsTable rows={view.rows} />
      )}
      {view.nextHref === null && view.firstHref === null ? null : (
        <nav aria-label={t("fanOuts.pager")}>
          <ul className="flex flex-wrap gap-4 text-sm">
            {view.firstHref === null ? null : (
              <li>
                <Link
                  href={view.firstHref as Route}
                  className="text-primary underline-offset-2 hover:underline"
                >
                  {t("fanOuts.newest")}
                </Link>
              </li>
            )}
            {view.nextHref === null ? null : (
              <li>
                <Link
                  href={view.nextHref as Route}
                  className="text-primary underline-offset-2 hover:underline"
                >
                  {t("fanOuts.older")}
                </Link>
              </li>
            )}
          </ul>
        </nav>
      )}
    </div>
  );
}
