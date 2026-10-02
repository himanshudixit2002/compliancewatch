import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { AdminNotificationsView } from "@/features/admin-notifications";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.notifications");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function AdminNotificationsPage() {
  const session = await requireScreenSession(SCREEN);
  return <AdminNotificationsView view={{ channels: [], digests: [], dispatchLog: [], recentBroadcasts: [], totalNotifications: 0, deliveryRate: 0 }} />;
}
