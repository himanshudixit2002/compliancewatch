import type { ReactNode } from "react";
import type { Route } from "next";
import Link from "next/link";
import { EmptyState, PageHeader, StatusChip, Timeline } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDateTime, formatDueDate } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  businessTone,
  completionRate,
  completionTone,
  urgentTone,
  type DashboardBusiness,
  type DashboardSummary,
  type UrgentAction,
} from "../model/dashboard";

export interface DashboardViewProps {
  view: DashboardSummary;
  businessHref: (businessId: string) => Route;
  obligationHref: (businessId: string, obligationId: string) => Route;
  /** Today, for the due dates; tests pass a fixed instant. */
  now?: Date;
}

function dueText(dueDate: string, now: Date | undefined): string {
  return formatDueDate(
    dueDate,
    {
      today: t("date.today"),
      tomorrow: t("date.tomorrow"),
      inDays: (count) => t("date.inDays", { count }),
      overdue: (count) => t("date.overdueBy", { count }),
    },
    now,
  );
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <h2 id={id} className="text-lg font-semibold text-fg">
        {title}
      </h2>
      {children}
    </section>
  );
}

function UrgentActions({
  actions,
  obligationHref,
  now,
}: {
  actions: readonly UrgentAction[];
  obligationHref: DashboardViewProps["obligationHref"];
  now: Date | undefined;
}) {
  if (actions.length === 0) {
    return (
      <EmptyState
        heading="h3"
        title={t("dashboard.urgentEmptyTitle")}
        body={t("dashboard.urgentEmptyBody")}
      />
    );
  }
  return (
    <ul className="flex flex-col gap-2">
      {actions.map((action) => {
        const tone = urgentTone(action, now);
        return (
          <li
            key={`${action.businessId}/${action.obligationId}`}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line p-3"
          >
            <Link
              href={obligationHref(action.businessId, action.obligationId)}
              className="font-medium text-primary hover:underline"
            >
              {action.title}
            </Link>
            <StatusChip
              status={tone === "danger" ? "overdue" : "due"}
              tone={tone}
              label={dueText(action.dueDate, now)}
            />
          </li>
        );
      })}
    </ul>
  );
}

function Businesses({
  businesses,
  businessHref,
}: {
  businesses: readonly DashboardBusiness[];
  businessHref: DashboardViewProps["businessHref"];
}) {
  return (
    <ul className="flex flex-col gap-2">
      {businesses.map((business) => {
        const tone = businessTone(business);
        return (
          <li
            key={business.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line p-3"
          >
            <div className="flex flex-col gap-0.5">
              <Link
                href={businessHref(business.id)}
                className="font-medium text-primary hover:underline"
              >
                {business.name}
              </Link>
              <span className="text-xs text-fg-muted">
                {t("dashboard.businessOpen", { count: business.openObligations })}
              </span>
            </div>
            <StatusChip
              status={tone === "danger" ? "overdue" : "up_to_date"}
              tone={tone}
              label={
                tone === "danger"
                  ? t("dashboard.businessOverdue", { count: business.overdueObligations })
                  : t("dashboard.businessUpToDate")
              }
            />
          </li>
        );
      })}
    </ul>
  );
}

/** The owner's compliance overview: obligation counts, urgent actions, activity and businesses. */
export function DashboardView({ view, businessHref, obligationHref, now }: DashboardViewProps) {
  const rate = completionRate(view);
  return (
    <div data-slot="dashboard" className="flex flex-col gap-8">
      <PageHeader title={t("dashboard.title")} description={t("dashboard.intro")} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={t("dashboard.overdue")}
          value={view.overdue}
          tone={view.overdue > 0 ? "danger" : "neutral"}
        />
        <StatCard label={t("dashboard.dueThisWeek")} value={view.dueThisWeek} tone="warning" />
        <StatCard label={t("dashboard.completed")} value={view.completed} tone="success" />
        <StatCard
          label={t("dashboard.completionRate")}
          value={rate === null ? t("common.none") : t("dashboard.percent", { value: rate })}
          tone={completionTone(rate)}
          hint={t("dashboard.completionRateHint")}
        />
      </div>
      <div className="grid gap-8 lg:grid-cols-2">
        <Section id="dashboard-urgent" title={t("dashboard.urgentTitle")}>
          <UrgentActions actions={view.urgentActions} obligationHref={obligationHref} now={now} />
        </Section>
        <Section id="dashboard-activity" title={t("dashboard.activityTitle")}>
          {view.activities.length === 0 ? (
            <EmptyState
              heading="h3"
              title={t("dashboard.activityEmptyTitle")}
              body={t("dashboard.activityEmptyBody")}
            />
          ) : (
            <Timeline
              events={view.activities.map((activity) => ({
                id: activity.id,
                label: formatDateTime(activity.at),
                dateTime: activity.at,
                title: activity.description,
              }))}
            />
          )}
        </Section>
      </div>
      {view.businesses.length > 0 ? (
        <Section id="dashboard-businesses" title={t("dashboard.businessesTitle")}>
          <Businesses businesses={view.businesses} businessHref={businessHref} />
        </Section>
      ) : null}
    </div>
  );
}
