import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { DashboardViewComponent } from "@/features/dashboard";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("owner.dashboard");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function OwnerDashboardPage() {
  const session = await requireScreenSession(SCREEN);
  return (
    <DashboardViewComponent
      view={{
        complianceScore: 0,
        overdueObligations: 0,
        dueThisWeek: 0,
        completedObligations: 0,
        businesses: [],
        recentActivities: [],
        urgentActions: [],
        filter: "all",
        sort: "updated",
      }}
      businessHref={(id) => `/b/${id}`}
      obligationHref={() => ""}
      href={() => ""}
    />
  );
}
