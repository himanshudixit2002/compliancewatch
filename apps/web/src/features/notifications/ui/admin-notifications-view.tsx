import type { Route } from "next";
import Link from "next/link";
import { Button, EmptyState, Field, Input, PageHeader } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { ServiceError, type ServiceErrorLike } from "@/shared/ui/service-error";
import type { AdminNotificationsView as AdminNotificationsViewModel } from "../model/history";
import { LOOKUP_FIELDS, type LookupRead } from "../model/lookup";
import { deliveryLabel, stateOptions } from "../model/notifications";
import { HistoryPager } from "./history-pager";
import { NotificationsTable } from "./notifications-table";
import { StateFilter } from "./state-filter";

export interface AdminNotificationsViewProps {
  title: string;
  crumbs: readonly Crumb[];
  /** The console itself, without a query: the forms' action. */
  pageHref: string;
  templatesHref: string;
  lookup: LookupRead;
  /** The history the lookup found; null before a lookup, or when the read failed. */
  view: AdminNotificationsViewModel | null;
  /** The failed read, shown under the form so the lookup can be corrected. */
  error?: ServiceErrorLike;
}

function lookupValues(lookup: LookupRead): { tenant: string; business: string } {
  if (lookup.kind === "ok")
    return { tenant: lookup.lookup.tenantId, business: lookup.lookup.businessId };
  if (lookup.kind === "invalid") return lookup.values;
  return { tenant: "", business: "" };
}

/**
 * The notification console: read-only, one business of one tenant at a time, because the
 * notification routes are tenant-scoped. The lookup is a GET form (tenant id and business id are
 * not personal data), then the business's history with the delivery state filter, the masked
 * addresses and the way to older pages. Nothing here sends or resends a message.
 */
export function AdminNotificationsView({
  title,
  crumbs,
  pageHref,
  templatesHref,
  lookup,
  view,
  error,
}: AdminNotificationsViewProps) {
  const values = lookupValues(lookup);
  const errors = lookup.kind === "invalid" ? lookup.errors : {};
  return (
    <div data-slot="admin-notifications" className="flex max-w-5xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("adminNotifications.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
        actions={
          <Link
            href={templatesHref as Route}
            className="text-sm text-primary underline-offset-2 hover:underline"
          >
            {t("adminNotifications.templatesLink")}
          </Link>
        }
      />
      <form
        method="get"
        action={pageHref}
        aria-label={t("adminNotifications.lookupLabel")}
        data-slot="notification-lookup"
        noValidate
        className="grid max-w-3xl items-end gap-3 sm:grid-cols-[1fr_1fr_auto]"
      >
        <Field
          id="lookup-tenant"
          label={t("adminNotifications.tenant")}
          error={errors.tenant}
          required
        >
          <Input
            name={LOOKUP_FIELDS.tenant}
            defaultValue={values.tenant}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Field
          id="lookup-business"
          label={t("adminNotifications.business")}
          error={errors.business}
          required
        >
          <Input
            name={LOOKUP_FIELDS.business}
            defaultValue={values.business}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Button type="submit" variant="secondary">
          {t("adminNotifications.lookup")}
        </Button>
      </form>
      {lookup.kind === "ok" ? (
        <section aria-labelledby="admin-notifications-history" className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h2 id="admin-notifications-history" className="text-lg font-semibold text-fg">
              {t("adminNotifications.historyTitle")}
            </h2>
            <p className="text-sm text-fg-muted" data-slot="lookup-facts">
              {t("adminNotifications.historyFacts", {
                business: lookup.lookup.businessId,
                tenant: lookup.lookup.tenantId,
              })}
            </p>
          </div>
          <StateFilter
            action={pageHref}
            state={view?.filter.state}
            options={stateOptions()}
            keep={{ tenant: lookup.lookup.tenantId, business: lookup.lookup.businessId }}
          />
          {error !== undefined ? <ServiceError error={error} /> : null}
          {view === null ? null : view.rows.length === 0 ? (
            view.filter.state === undefined ? (
              <EmptyState
                title={t("adminNotifications.emptyTitle")}
                body={t("adminNotifications.emptyBody")}
              />
            ) : (
              <EmptyState
                title={t("notificationLog.emptyStateTitle")}
                body={t("adminNotifications.emptyStateBody", {
                  state: deliveryLabel(view.filter.state),
                })}
              />
            )
          ) : (
            <NotificationsTable rows={view.rows} />
          )}
          {view === null ? null : (
            <HistoryPager nextHref={view.nextHref} firstHref={view.firstHref} />
          )}
        </section>
      ) : (
        <p className="max-w-prose text-sm text-fg-muted">{t("adminNotifications.lookupHelp")}</p>
      )}
    </div>
  );
}
