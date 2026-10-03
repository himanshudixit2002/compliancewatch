import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { AdminSourcesViewComponent } from "@/features/admin-sources";
import { emptyAdminSources } from "@/features/admin-sources/model/sources";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.sources");

export const metadata: Metadata = { title: "Data sources" };

export const dynamic = "force-dynamic";

export default async function AdminSourcesPage() {
  await requireScreenSession(SCREEN);

  return <AdminSourcesViewComponent view={emptyAdminSources()} />;
}