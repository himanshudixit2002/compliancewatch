import type { Route } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
import { EmptyState, PageHeader, cn } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t, type MessageKey } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { NotLegalAdvice } from "@/shared/ui/not-legal-advice";
import { StatCard } from "@/shared/ui/stat-card";
import { RESULT_FILTERS, filterLabel, impactHref, type ResultFilter } from "../model/impact";
import type { ChangeImpactView as ChangeImpactViewModel } from "../queries";
import { BulkPanel, type BulkAction } from "./bulk-panel";
import { ClientsTable } from "./clients-table";

export interface ChangeImpactViewProps {
  title: string;
  crumbs: readonly Crumb[];
  /** The screen itself, without a query: where the filter links point. */
  pageHref: string;
  view: ChangeImpactViewModel;
  sendAction: BulkAction;
  idempotencyInput: ReactNode;
}

const EMPTY: Readonly<Record<ResultFilter, { title: MessageKey; body: MessageKey }>> = {
  applies: { title: "changeImpact.empty.appliesTitle", body: "changeImpact.empty.appliesBody" },
  unsure: { title: "changeImpact.empty.unsureTitle", body: "changeImpact.empty.unsureBody" },
  not_applicable: {
    title: "changeImpact.empty.notApplicableTitle",
    body: "changeImpact.empty.notApplicableBody",
  },
  all: { title: "changeImpact.empty.allTitle", body: "changeImpact.empty.allBody" },
};

/**
 * Which of a CA firm's clients a change affects: the change and its counts over every business of
 * the firm with a decision of it, how far its fan-out got, the clients with each business's
 * latest result (the affected ones by default, any other result by the filter), and the one bulk
 * change card to the affected clients' own people. Every number is the engine's; nothing is
 * worked out here.
 */
export function ChangeImpactView({
  title,
  crumbs,
  pageHref,
  view,
  sendAction,
  idempotencyInput,
}: ChangeImpactViewProps) {
  return (
    <div data-slot="change-impact" className="flex max-w-5xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("changeImpact.intro", { name: view.name, title: view.title })}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <p className="text-sm text-fg-muted" data-slot="change-facts">
        {t("changeImpact.facts", { name: view.name, status: view.status })} {view.fanOut}
      </p>
      <div className="grid gap-3 sm:grid-cols-3" data-slot="impact-counts">
        <div data-count="applies">
          <StatCard label={t("applicability.applies")} value={view.counts.applies} tone="success" />
        </div>
        <div data-count="unsure">
          <StatCard label={t("applicability.unsure")} value={view.counts.unsure} tone="warning" />
        </div>
        <div data-count="not_applicable">
          <StatCard label={t("applicability.notApplicable")} value={view.counts.notApplicable} />
        </div>
      </div>
      <nav aria-label={t("changeImpact.filterLabel")}>
        <ul className="flex flex-wrap gap-2 text-sm">
          {RESULT_FILTERS.map((filter) => (
            <li key={filter}>
              <Link
                href={impactHref(pageHref, filter) as Route}
                aria-current={filter === view.filter ? "true" : undefined}
                data-filter={filter}
                className={cn(
                  "inline-flex items-center rounded-full border px-3 py-1 text-sm font-medium underline-offset-2 hover:underline",
                  filter === view.filter
                    ? "border-primary bg-primary text-primary-fg"
                    : "border-line-strong bg-surface text-fg",
                )}
              >
                {filterLabel(filter)}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      {view.clients.length === 0 ? (
        view.firstHref === null ? (
          <EmptyState title={t(EMPTY[view.filter].title)} body={t(EMPTY[view.filter].body)} />
        ) : (
          <EmptyState title={t("changeImpact.end.title")} body={t("changeImpact.end.body")} />
        )
      ) : (
        <ClientsTable clients={view.clients} />
      )}
      {view.nextHref === null && view.firstHref === null ? null : (
        <nav aria-label={t("changeImpact.pager")}>
          <ul className="flex flex-wrap gap-4 text-sm">
            {view.firstHref === null ? null : (
              <li>
                <Link
                  href={view.firstHref as Route}
                  className="text-primary underline-offset-2 hover:underline"
                >
                  {t("changeImpact.first")}
                </Link>
              </li>
            )}
            {view.nextHref === null ? null : (
              <li>
                <Link
                  href={view.nextHref as Route}
                  className="text-primary underline-offset-2 hover:underline"
                >
                  {t("changeImpact.next")}
                </Link>
              </li>
            )}
          </ul>
        </nav>
      )}
      <BulkPanel
        action={sendAction}
        targets={view.targets}
        cut={view.targetsCut}
        idempotencyInput={idempotencyInput}
      />
      <NotLegalAdvice />
    </div>
  );
}
