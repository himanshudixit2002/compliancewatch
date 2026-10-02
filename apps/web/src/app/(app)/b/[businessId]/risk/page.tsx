import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { RiskViewComponent } from "@/features/risk";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("owner.risk");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function RiskPage({ params }: { params: { businessId: string } }) {
  const session = await requireScreenSession(SCREEN);
  return (
    <RiskViewComponent
      view={{
        businessId: params.businessId,
        risks: [],
        totalCount: 0,
        highCount: 0,
        mediumCount: 0,
        lowCount: 0,
        mitigatedCount: 0,
        filter: "all",
        sort: "severity",
      }}
      businessId={params.businessId}
      href={() => ""}
    />
  );
}
