import type { Metadata } from "next";
import { AdminHomeView, adminToolGroups } from "@/features/admin-home";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.home");

export const metadata: Metadata = { title: SCREEN.title };

export default function AdminHomePage() {
  return <AdminHomeView groups={adminToolGroups()} />;
}
