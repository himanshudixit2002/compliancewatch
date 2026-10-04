import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { toAwaitedItem } from "@/entities/screen/mappers";
import {
  AdminNotificationView,
  TenantNeededView,
  getAdminNotification,
  readTenant,
} from "@/features/notifications";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, isVisibleTo, screenById } from "@/shared/config/screens";
import { isUuid } from "@/shared/lib/identifiers";
import { withQuery } from "@/shared/lib/url";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.notification");
const RESEND = screenById("admin.notification.resend");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ notificationId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function AdminNotificationPage({ params, searchParams }: Props) {
  const { notificationId } = await params;
  const session = await requireScreenSession(SCREEN, { notificationId });
  if (!isUuid(notificationId)) notFound();
  const tenant = readTenant(await searchParams);
  const pageHref = hrefFor(SCREEN, { notificationId });
  const crumbs = breadcrumbsFor("admin.notification", { notificationId });
  if (tenant.kind !== "ok") {
    return (
      <TenantNeededView
        title={SCREEN.title}
        crumbs={crumbs}
        action={pageHref}
        value={tenant.kind === "invalid" ? tenant.value : ""}
        {...(tenant.kind === "invalid" ? { error: tenant.error } : {})}
      />
    );
  }
  const page = await getAdminNotification(session, tenant.tenantId, notificationId);
  if (!page.ok) {
    if (page.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={page.error} />;
  }
  const named = crumbs.map((crumb) => {
    if (crumb.id === "admin.notifications") return { ...crumb, href: page.value.listHref };
    if (crumb.id === SCREEN.id) {
      return {
        ...crumb,
        href: withQuery(pageHref, { tenant: tenant.tenantId }),
        label: page.value.detail.title,
      };
    }
    return crumb;
  });
  const resend = isVisibleTo(RESEND, session.roles, session.tenantKind)
    ? { title: RESEND.title, waitingFor: RESEND.awaits.map(toAwaitedItem) }
    : null;
  return <AdminNotificationView crumbs={named} view={page.value} resend={resend} />;
}
