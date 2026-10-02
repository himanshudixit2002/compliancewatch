import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { ReviewQueueViewComponent } from "@/features/review-queue";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.review");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function ReviewQueuePage() {
  const session = await requireScreenSession(SCREEN);
  return (
    <ReviewQueueViewComponent
      view={{
        items: [],
        totalCount: 0,
        pendingCount: 0,
        approvedCount: 0,
        rejectedCount: 0,
        filter: "pending",
        sort: "created",
      }}
      detailHref={() => ""}
    />
  );
}
