import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { ChangesView } from "@/features/changes";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("owner.changes");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function ChangesPage({ params }: { params: { businessId: string } }) {
  const session = await requireScreenSession(SCREEN);
  return (
    <ChangesView
      view={{ changes: [], totalCount: 0, applicableCount: 0, pendingReviewCount: 0, period: "" }}
      businessId={params.businessId}
      href={() => ""}
    />
  );
}
