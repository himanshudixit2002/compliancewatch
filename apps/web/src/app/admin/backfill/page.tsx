import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { AdminBackfillViewComponent } from "@/features/admin-backfill";
import { emptyAdminBackfill } from "@/features/admin-backfill/model/backfill";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.backfill");

export const metadata: Metadata = { title: "Backfill" };

export const dynamic = "force-dynamic";

export default async function AdminBackfillPage() {
  await requireScreenSession(SCREEN);

  return <AdminBackfillViewComponent view={emptyAdminBackfill()} />;
}