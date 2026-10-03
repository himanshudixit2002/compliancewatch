import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { AuditViewComponent } from "@/features/admin-audit";
import { emptyAudit } from "@/features/admin-audit/model/audit";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.audit");

export const metadata: Metadata = { title: "Audit log" };

export const dynamic = "force-dynamic";

export default async function AdminAuditPage() {
  await requireScreenSession(SCREEN);

  return <AuditViewComponent view={emptyAudit()} />;
}