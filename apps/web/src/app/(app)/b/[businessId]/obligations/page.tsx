import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { ObligationView } from "@/features/obligations";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("owner.obligations");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function ObligationsPage({ params }: { params: { businessId: string } }) {
  const session = await requireScreenSession(SCREEN);
  return (
    <ObligationView
      view={{ obligations: [], totalCount: 0, dueSoonCount: 0, overdueCount: 0, completionRate: 0, filter: "all", sort: "due_date" }}
      businessId={params.businessId}
      href={() => ""}
    />
  );
}
