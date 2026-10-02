import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { NotificationDetail, notificationById } from "@/features/notifications";
import { requireScreenSession } from "@/server/dal";
import { hrefFor, screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.notification");
const LIST_SCREEN = screenById("owner.notifications");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function NotificationDetailPage({ params }: Props) {
  const session = await requireScreenSession(SCREEN);
  const { id } = await params;
  const result = await notificationById(id);
  if (!result.ok) {
    if (result.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={result.error} />;
  }
  return <NotificationDetail view={result.value} backHref={hrefFor(LIST_SCREEN)} />;
}
