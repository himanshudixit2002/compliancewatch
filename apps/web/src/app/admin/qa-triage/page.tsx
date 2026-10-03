import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { AdminQaTriageViewComponent } from "@/features/admin-qa-triage";
import { emptyAdminQaTriage } from "@/features/admin-qa-triage/model/qa-triage";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.qa-triage");

export const metadata: Metadata = { title: "QA triage" };

export const dynamic = "force-dynamic";

export default async function AdminQaTriagePage() {
  await requireScreenSession(SCREEN);

  return <AdminQaTriageViewComponent view={emptyAdminQaTriage()} />;
}