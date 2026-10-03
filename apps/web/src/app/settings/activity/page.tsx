import type { Metadata } from "next";
import { ActivityView, emptyActivity } from "@/features/settings-activity";
import { requireScreenSession } from "@/server/dal";
import { settingsHeaderLinks } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("owner.settings.activity");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function ActivityLogPage() {
  const session = await requireScreenSession(SCREEN);
  const { crumbs, tabs } = settingsHeaderLinks(SCREEN, session);
  return <ActivityView title={SCREEN.title} view={emptyActivity()} crumbs={crumbs} tabs={tabs} />;
}
