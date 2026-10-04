import type { Route } from "next";
import Link from "next/link";
import { Banner, Button, Field, Input, PageHeader } from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import type { AdminNotificationView as AdminNotificationViewModel } from "../model/history";
import { LOOKUP_FIELDS } from "../model/lookup";
import { NotificationDetail } from "./notification-detail";

/** An action the record would offer that waits for a backend, from its registry entry. */
export interface WaitingAction {
  title: string;
  waitingFor: readonly { method: string; path: string; owner: string }[];
}

export interface AdminNotificationViewProps {
  crumbs: readonly Crumb[];
  view: AdminNotificationViewModel;
  /** Resending, while it waits for its hardened route; null for a role it is not for. */
  resend: WaitingAction | null;
}

/**
 * One notification of the tenant the console looked up: its delivery record with the ids an
 * operator traces a delivery by, and what resending waits for. Read-only.
 */
export function AdminNotificationView({ crumbs, view, resend }: AdminNotificationViewProps) {
  const { detail } = view;
  return (
    <div data-slot="admin-notification" className="flex max-w-4xl flex-col gap-6">
      <PageHeader
        title={detail.title}
        description={t("notificationLog.detailIntro", {
          template: detail.templateKey,
          occasion: detail.occasionLabel,
          language: detail.languageLabel,
        })}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <p className="text-sm text-fg-muted" data-slot="notification-tenant">
        {t("adminNotifications.tenantFact", { tenant: view.tenantId })}
      </p>
      <Link
        href={view.listHref as Route}
        className="inline-flex w-fit items-center gap-1 text-sm text-fg-muted hover:text-fg"
      >
        <span aria-hidden="true">←</span>
        <span>{t("adminNotifications.backToList")}</span>
      </Link>
      <NotificationDetail detail={detail} fallbackHref={view.fallbackHref} showIds>
        {resend === null ? null : (
          <Banner tone="info" title={t("adminNotifications.resendTitle", { title: resend.title })}>
            <p>{t("adminNotifications.resendBody")}</p>
            <ul data-slot="resend-awaits" className="mt-1 flex flex-col gap-0.5">
              {resend.waitingFor.map((item) => (
                <li key={`${item.method} ${item.path}`}>
                  <code className="font-mono text-xs">{`${item.method} ${item.path}`}</code> (
                  {item.owner})
                </li>
              ))}
            </ul>
          </Banner>
        )}
      </NotificationDetail>
    </div>
  );
}

export interface TenantNeededViewProps {
  title: string;
  crumbs: readonly Crumb[];
  /** The notification's own page, which the form reloads with the tenant. */
  action: string;
  value: string;
  error?: string;
}

/**
 * A notification opened without its tenant: the routes are tenant-scoped, so the page asks for
 * the tenant first, as a GET form back to the same notification.
 */
export function TenantNeededView({ title, crumbs, action, value, error }: TenantNeededViewProps) {
  return (
    <div data-slot="tenant-needed" className="flex max-w-3xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("adminNotifications.tenantNeeded")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <form
        method="get"
        action={action}
        aria-label={t("adminNotifications.tenantFormLabel")}
        noValidate
        className="flex flex-wrap items-end gap-3"
      >
        <Field
          id="notification-tenant"
          label={t("adminNotifications.tenant")}
          error={error}
          required
          className="w-96"
        >
          <Input
            name={LOOKUP_FIELDS.tenant}
            defaultValue={value}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Button type="submit" variant="secondary">
          {t("adminNotifications.open")}
        </Button>
      </form>
    </div>
  );
}
