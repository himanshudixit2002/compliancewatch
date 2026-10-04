import type { Route } from "next";
import Link from "next/link";
import { PageHeader } from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { SectionNav } from "@/shared/ui/section-nav";
import type { ReminderView as ReminderViewModel } from "../model/history";
import { NotificationDetail } from "./notification-detail";

export interface ReminderViewProps {
  view: ReminderViewModel;
  header: { crumbs: readonly Crumb[]; tabs: readonly NavLink[] };
}

/** One notification sent for the business, named by its template, with its delivery record. */
export function ReminderView({ view, header }: ReminderViewProps) {
  const { detail } = view;
  return (
    <div data-slot="reminder" className="flex max-w-4xl flex-col gap-6">
      <div className="flex flex-col gap-4">
        <PageHeader
          title={detail.title}
          description={t("notificationLog.detailIntro", {
            template: detail.templateKey,
            occasion: detail.occasionLabel,
            language: detail.languageLabel,
          })}
          breadcrumbs={<Breadcrumbs crumbs={header.crumbs} />}
        />
        <SectionNav items={header.tabs} label={t("business.tabs")} />
      </div>
      <Link
        href={view.listHref as Route}
        className="inline-flex w-fit items-center gap-1 text-sm text-fg-muted hover:text-fg"
      >
        <span aria-hidden="true">←</span>
        <span>{t("notificationLog.backToList")}</span>
      </Link>
      <NotificationDetail detail={detail} fallbackHref={view.fallbackHref} />
    </div>
  );
}
