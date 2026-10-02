import type { Metadata } from "next";
import {
  CHANGE_FIELDS,
  ConsentSettings,
  changeConsent,
  getConsentSettings,
} from "@/features/consents";
import { requireScreenSession } from "@/server/dal";
import { settingsHeaderLinks } from "@/shared/config/nav";
import { hrefFor, isVisibleTo, screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.settings.consents");
const ONBOARDING = screenById("owner.onboarding");
const LEGAL = screenById("system.legal");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function ConsentSettingsPage() {
  const session = await requireScreenSession(SCREEN);
  const settings = await getConsentSettings(session);
  if (!settings.ok) return <ServiceError heading={SCREEN.title} error={settings.error} />;
  const { crumbs, tabs } = settingsHeaderLinks(SCREEN, session);
  return (
    <ConsentSettings
      title={SCREEN.title}
      view={settings.value}
      crumbs={crumbs}
      tabs={tabs}
      action={changeConsent}
      fields={CHANGE_FIELDS}
      onboardingHref={
        isVisibleTo(ONBOARDING, session.roles, session.tenantKind) ? hrefFor(ONBOARDING) : null
      }
      dataRightsHref={hrefFor(screenById("owner.settings.data-rights"))}
      documentHref={(doc) => hrefFor(LEGAL, { doc })}
    />
  );
}
