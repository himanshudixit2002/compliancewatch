import type { Metadata } from "next";
import { AdminHomeView, adminToolGroups, getAdminHome } from "@/features/admin-home";
import { requireScreenSession } from "@/server/dal";
import { HEALTH_TIMEOUT_MS } from "@/server/health";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.home");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function AdminHomePage() {
  const session = await requireScreenSession(SCREEN);
  const home = await getAdminHome(session);
  return (
    <AdminHomeView
      groups={adminToolGroups()}
      tiles={home.tiles}
      services={home.services}
      probeTimeoutSeconds={HEALTH_TIMEOUT_MS / 1000}
    />
  );
}
