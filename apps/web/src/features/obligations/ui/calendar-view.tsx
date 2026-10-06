import { PageHeader } from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { NotLegalAdvice } from "@/shared/ui/not-legal-advice";
import { SectionNav } from "@/shared/ui/section-nav";
import type { CalendarPageView } from "../queries";
import type { CalendarMonthAnswer } from "./calendar-shared";
import { ObligationCalendar } from "./obligation-calendar";

export interface CalendarViewProps {
  title: string;
  view: CalendarPageView;
  header: { crumbs: readonly Crumb[]; tabs: readonly NavLink[] };
  /** Reads another month for the grid (a server action bound to the business). */
  load: (month: string) => Promise<CalendarMonthAnswer>;
  /** The calendar itself, without a query. */
  pageHref: string;
  /** The list, for everything outside the month. */
  listHref: string;
}

/**
 * A month of the business's obligations by due day in India: how many fall due, the grid with
 * each due day marked, and the obligations of the day chosen.
 */
export function CalendarView({ title, view, header, load, pageHref, listHref }: CalendarViewProps) {
  const { calendar } = view;
  return (
    <div data-slot="calendar" className="flex max-w-3xl flex-col gap-6">
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
      <ObligationCalendar
        initial={{
          month: calendar.month,
          days: calendar.days,
          selected: calendar.selected,
          total: calendar.total,
          cut: calendar.cut,
        }}
        load={load}
        pathname={pageHref}
        listHref={listHref}
      />
      <NotLegalAdvice />
    </div>
  );
}
