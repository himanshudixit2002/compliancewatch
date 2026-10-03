import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { AdminTenantsViewComponent, emptyAdminTenants } from "@/features/admin-tenants";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.tenants");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function AdminTenantsPage() {
  await requireScreenSession(SCREEN);

  return <AdminTenantsViewComponent view={emptyAdminTenants()} onImpersonate={() => {}} />;
}
