import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { AdminErrorReportsViewComponent } from "@/features/admin-error-reports";
import { emptyAdminErrorReports } from "@/features/admin-error-reports/model/error-reports";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.error-reports");

export const metadata: Metadata = { title: "Error reports" };

export const dynamic = "force-dynamic";

export default async function AdminErrorReportsPage() {
  await requireScreenSession(SCREEN);

  return <AdminErrorReportsViewComponent view={emptyAdminErrorReports()} />;
}