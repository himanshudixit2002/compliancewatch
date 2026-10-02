import type { Metadata } from "next";
import {
  NotificationSettings,
  PREFERENCE_FIELDS,
  RECIPIENT_FIELDS,
  chooseRecipient,
  forgetRecipient,
  getNotificationSettings,
  savePreference,
} from "@/features/notification-preferences";
import { requireScreenSession } from "@/server/dal";
import { settingsHeaderLinks } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.settings.notifications");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function NotificationSettingsPage() {
  const session = await requireScreenSession(SCREEN);
  const settings = await getNotificationSettings(session);
  if (!settings.ok) return <ServiceError heading={SCREEN.title} error={settings.error} />;
  const { crumbs, tabs } = settingsHeaderLinks(SCREEN, session);
  return (
    <NotificationSettings
      title={SCREEN.title}
      view={settings.value}
      crumbs={crumbs}
      tabs={tabs}
      chooseRecipient={chooseRecipient}
      forgetRecipient={forgetRecipient}
      savePreference={savePreference}
      fields={{ recipient: RECIPIENT_FIELDS, preference: PREFERENCE_FIELDS }}
      consentsHref={hrefFor(screenById("owner.settings.consents"))}
    />
  );
}
