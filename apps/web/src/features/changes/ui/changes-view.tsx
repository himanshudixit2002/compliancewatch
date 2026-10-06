import type { Route } from "next";
import Link from "next/link";
import { EmptyState, PageHeader } from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { NotLegalAdvice } from "@/shared/ui/not-legal-advice";
import { SectionNav } from "@/shared/ui/section-nav";
import type { ChangesView as ChangesViewModel } from "../queries";
import { ChangeCard } from "./change-card";

export interface ChangesViewProps {
  title: string;
  view: ChangesViewModel;
  header: { crumbs: readonly Crumb[]; tabs: readonly NavLink[] };
}

/**
 * The rulebook's published changes, newest first, each as a card with whether it applies to this
 * business; a page at a time by the service's cursor. Before anything is published the page says
 * so rather than showing an empty list.
 */
export function ChangesView({ title, view, header }: ChangesViewProps) {
  return (
    <div data-slot="changes" className="flex max-w-4xl flex-col gap-6">
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
      <p className="max-w-prose text-sm text-fg-muted">{t("changes.intro")}</p>
      {view.cards.length === 0 ? (
        view.firstHref === null ? (
          <EmptyState title={t("changes.empty.title")} body={t("changes.empty.body")} />
        ) : (
          <EmptyState title={t("changes.end.title")} body={t("changes.end.body")} />
        )
      ) : (
        <div className="flex flex-col gap-4" data-slot="change-cards">
          {view.cards.map((card) => (
            <ChangeCard key={card.id} card={card} />
          ))}
        </div>
      )}
      {view.nextHref === null && view.firstHref === null ? null : (
        <nav aria-label={t("changes.pager")}>
          <ul className="flex flex-wrap gap-4 text-sm">
            {view.firstHref === null ? null : (
              <li>
                <Link
                  href={view.firstHref as Route}
                  className="text-primary underline-offset-2 hover:underline"
                >
                  {t("changes.newest")}
                </Link>
              </li>
            )}
            {view.nextHref === null ? null : (
              <li>
                <Link
                  href={view.nextHref as Route}
                  className="text-primary underline-offset-2 hover:underline"
                >
                  {t("changes.older")}
                </Link>
              </li>
            )}
          </ul>
        </nav>
      )}
      <NotLegalAdvice />
    </div>
  );
}
