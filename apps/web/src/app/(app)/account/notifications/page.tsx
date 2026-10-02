import type { Metadata } from "next";
import { toSessionDto } from "@/entities/session/mappers";
import { NotificationsList, notifications } from "@/features/notifications";
import { requireScreenSession } from "@/server/dal";
import { hrefFor, screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.notifications");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function NotificationsPage() {
  const session = await requireScreenSession(SCREEN);
  const result = await notifications();
  if (!result.ok) {
    return <ServiceError heading={SCREEN.title} error={result.error} />;
  }
  const counts = result.value.reduce(
    (acc, item) => {
      acc.total += 1;
      if (item.status === "sent") acc.sent += 1;
      if (item.status === "delivered") acc.delivered += 1;
      if (item.status === "failed") acc.failed += 1;
      return acc;
    },
    { total: 0, sent: 0, delivered: 0, failed: 0 },
  );
  return (
    <NotificationsList
      view={{ items: result.value, counts }}
      search={{ value: "", onChange: () => undefined }}
      baseHref={hrefFor(SCREEN)}
    />
  );
}
