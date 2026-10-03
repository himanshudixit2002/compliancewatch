import type { Metadata } from "next";
import { RecipientsView, emptyRecipients } from "@/features/settings-notification-recipients";
import { requireScreenSession } from "@/server/dal";
import { settingsHeaderLinks } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("owner.settings.notification-recipients");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function NotificationRecipientsPage() {
  const session = await requireScreenSession(SCREEN);
  const { crumbs, tabs } = settingsHeaderLinks(SCREEN, session);
  return (
    <RecipientsView title={SCREEN.title} view={emptyRecipients()} crumbs={crumbs} tabs={tabs} />
  );
}
