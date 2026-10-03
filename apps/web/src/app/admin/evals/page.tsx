import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { AdminEvalsViewComponent } from "@/features/admin-evals";
import { emptyAdminEvals } from "@/features/admin-evals/model/evals";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.evals");

export const metadata: Metadata = { title: "LLM evaluations" };

export const dynamic = "force-dynamic";

export default async function AdminEvalsPage() {
  await requireScreenSession(SCREEN);

  return <AdminEvalsViewComponent view={emptyAdminEvals()} />;
}
