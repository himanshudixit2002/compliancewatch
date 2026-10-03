import type { Metadata } from "next";
import { DataRightsView, emptyDataRights } from "@/features/settings-data-rights";
import { requireScreenSession } from "@/server/dal";
import { settingsHeaderLinks } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("owner.settings.data-rights");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function DataRightsPage() {
  const session = await requireScreenSession(SCREEN);
  const { crumbs, tabs } = settingsHeaderLinks(SCREEN, session);
  return (
    <DataRightsView title={SCREEN.title} view={emptyDataRights()} crumbs={crumbs} tabs={tabs} />
  );
}
