import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { ReportViewComponent } from "@/features/reports";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("owner.reports");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function ReportsPage() {
  const session = await requireScreenSession(SCREEN);
  return (
    <ReportViewComponent
      view={{
        reports: [],
        businessId: "",
        totalCount: 0,
      }}
    />
  );
}
