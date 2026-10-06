import type { Metadata } from "next";
import { SystemView, getSystem } from "@/features/system";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.system");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function SystemPage() {
  await requireScreenSession(SCREEN);
  const system = await getSystem();
  return (
    <SystemView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.system")}
      rows={system.rows}
      summary={system.summary}
      facts={system.facts}
      probeTimeoutSeconds={system.probeTimeoutSeconds}
    />
  );
}
