import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { businessHeaderLinks } from "@/features/business";
import { ReminderView, getReminder } from "@/features/notifications";
import { requireScreenSession } from "@/server/dal";
import { hrefFor, screenById } from "@/shared/config/screens";
import { isUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.reminder");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ businessId: string; notificationId: string }>;
}

export default async function ReminderPage({ params }: Props) {
  const { businessId, notificationId } = await params;
  const session = await requireScreenSession(SCREEN, { businessId, notificationId });
  if (!isUuid(businessId) || !isUuid(notificationId)) notFound();
  const page = await getReminder(session, businessId, notificationId);
  if (!page.ok) {
    if (page.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={page.error} />;
  }
  const list = businessHeaderLinks(
    "owner.reminders",
    session,
    businessId,
    page.value.business.name,
  );
  const crumbs = [
    ...list.crumbs,
    {
      id: SCREEN.id,
      href: hrefFor(SCREEN, { businessId, notificationId }),
      label: page.value.detail.title,
    },
  ];
  return <ReminderView view={page.value} header={{ crumbs, tabs: list.tabs }} />;
}
