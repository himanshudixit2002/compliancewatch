import type { Metadata } from "next";
import { AdminHomeView, adminToolGroups } from "@/features/admin-home";
import { requireAdmin } from "@/server/dal";
import { hrefFor, screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.home");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function AdminHomePage() {
  await requireAdmin({ next: hrefFor(SCREEN) });
  return <AdminHomeView groups={adminToolGroups()} />;
}
