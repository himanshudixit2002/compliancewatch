import "server-only";

import type { ClientContext } from "@/server/api/services";
import { err, mapResult, ok, webError, type Result } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { withQuery } from "@/shared/lib/url";
import { notificationsGateway } from "./gateway";
import {
  historyHrefs,
  type AdminNotificationView,
  type AdminNotificationsView,
  type ReminderView,
  type RemindersView,
} from "./model/history";
import type { AdminLookup } from "./model/lookup";
import {
  HISTORY_PAGE_SIZE,
  notificationDetail,
  notificationRows,
  type HistoryFilter,
} from "./model/notifications";
import { templateRows, type TemplateRow } from "./model/templates";

/**
 * The reminders pages' reads: a business's notifications, a page at a time, and one of them, for
 * the session's tenant. The business is read first-hand from the profile service, which says
 * whether the tenant holds it (the notification service lists nothing, rather than refusing, for
 * a business it has no notification about); a notification of another business is not found
 * under this one.
 */
export interface QueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
}

export type QuerySession = NonNullable<ClientContext["session"]>;

export async function getReminders(
  session: QuerySession,
  businessId: string,
  filter: HistoryFilter,
  deps: QueryDeps = {},
): Promise<Result<RemindersView>> {
  const gateway = notificationsGateway({ session, fetchImpl: deps.fetchImpl });
  const [business, page] = await Promise.all([
    gateway.business(businessId),
    gateway.page(businessId, { ...filter, limit: HISTORY_PAGE_SIZE }),
  ]);
  if (!business.ok) return business;
  if (!page.ok) return page;
  const listHref = hrefFor(screenById("owner.reminders"), { businessId });
  const detail = screenById("owner.reminder");
  return ok({
    business: business.value,
    rows: notificationRows(page.value.items, (notificationId) =>
      hrefFor(detail, { businessId, notificationId }),
    ),
    filter,
    ...historyHrefs(listHref, filter, page.value.nextCursor),
  });
}

export async function getReminder(
  session: QuerySession,
  businessId: string,
  notificationId: string,
  deps: QueryDeps = {},
): Promise<Result<ReminderView>> {
  const gateway = notificationsGateway({ session, fetchImpl: deps.fetchImpl });
  const [business, record] = await Promise.all([
    gateway.business(businessId),
    gateway.get(notificationId),
  ]);
  if (!business.ok) return business;
  if (!record.ok) return record;
  if (record.value.businessId !== businessId) {
    return err(
      webError("not_found", "web-notification-not-found", t("notificationLog.notThisBusiness")),
    );
  }
  const detail = screenById("owner.reminder");
  const { fallbackOf } = record.value;
  return ok({
    business: business.value,
    detail: notificationDetail(record.value),
    listHref: hrefFor(screenById("owner.reminders"), { businessId }),
    fallbackHref:
      fallbackOf === null ? null : hrefFor(detail, { businessId, notificationId: fallbackOf }),
  });
}

function adminDetailHref(notificationId: string, tenantId: string, businessId: string): string {
  return withQuery(hrefFor(screenById("admin.notification"), { notificationId }), {
    tenant: tenantId,
    business: businessId,
  });
}

export async function getAdminNotifications(
  session: QuerySession,
  lookup: AdminLookup,
  filter: HistoryFilter,
  deps: QueryDeps = {},
): Promise<Result<AdminNotificationsView>> {
  const gateway = notificationsGateway({
    session,
    tenantId: lookup.tenantId,
    fetchImpl: deps.fetchImpl,
  });
  const page = await gateway.page(lookup.businessId, { ...filter, limit: HISTORY_PAGE_SIZE });
  if (!page.ok) return page;
  const keep = { tenant: lookup.tenantId, business: lookup.businessId };
  return ok({
    lookup,
    rows: notificationRows(page.value.items, (notificationId) =>
      adminDetailHref(notificationId, lookup.tenantId, lookup.businessId),
    ),
    filter,
    ...historyHrefs(
      hrefFor(screenById("admin.notifications")),
      filter,
      page.value.nextCursor,
      keep,
    ),
  });
}

export async function getAdminNotification(
  session: QuerySession,
  tenantId: string,
  notificationId: string,
  deps: QueryDeps = {},
): Promise<Result<AdminNotificationView>> {
  const record = await notificationsGateway({ session, tenantId, fetchImpl: deps.fetchImpl }).get(
    notificationId,
  );
  if (!record.ok) return record;
  const { businessId, fallbackOf } = record.value;
  return ok({
    tenantId,
    detail: notificationDetail(record.value),
    listHref: withQuery(hrefFor(screenById("admin.notifications")), {
      tenant: tenantId,
      business: businessId,
    }),
    fallbackHref: fallbackOf === null ? null : adminDetailHref(fallbackOf, tenantId, businessId),
  });
}

/** The message templates, for the template console; a global read. */
export async function getTemplates(deps: QueryDeps = {}): Promise<Result<TemplateRow[]>> {
  const templates = await notificationsGateway({
    session: null,
    fetchImpl: deps.fetchImpl,
  }).templates();
  return mapResult(templates, templateRows);
}
