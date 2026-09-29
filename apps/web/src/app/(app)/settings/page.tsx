import type { Metadata } from "next";
import { SettingsIndex, settingsIndexView } from "@/features/settings";
import { requireScreenSession } from "@/server/dal";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("owner.settings");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const session = await requireScreenSession(SCREEN);
  return (
    <SettingsIndex
      title={SCREEN.title}
      view={settingsIndexView({ roles: session.roles, tenantKind: session.tenantKind })}
    />
  );
}
