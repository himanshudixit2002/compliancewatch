import "server-only";

import type { ClientContext } from "@/server/api/services";
import { err, webError, ok, type Result } from "@/server/result";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { notificationsGateway } from "./gateway";
import { historyHrefs, type ReminderView, type RemindersView } from "./model/history";
import {
  HISTORY_PAGE_SIZE,
  notificationDetail,
  notificationRows,
  type HistoryFilter,
} from "./model/notifications";

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
