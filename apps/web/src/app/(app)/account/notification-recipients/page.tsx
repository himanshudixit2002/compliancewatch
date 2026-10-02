import type { Metadata } from "next";
import { toSessionDto } from "@/entities/session/mappers";
import { RecipientsView, recipients } from "@/features/notification-recipients";
import { requireScreenSession } from "@/server/dal";
import { settingsHeaderLinks } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.settings.notification-recipients");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function NotificationRecipientsPage() {
  const session = await requireScreenSession(SCREEN);
  const result = await recipients();
  if (!result.ok) {
    return <ServiceError heading={SCREEN.title} error={result.error} />;
  }
  const { crumbs, tabs } = settingsHeaderLinks(SCREEN, {
    roles: session.roles,
    tenantKind: session.tenantKind,
  });
  return (
    <RecipientsView
      title={SCREEN.title}
      items={result.value}
      crumbs={crumbs}
      tabs={tabs}
    />
  );
}
