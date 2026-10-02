import { Suspense } from "react";
import type { Metadata } from "next";
import { ReviewPage, ReviewPageSkeleton } from "@/features/admin-review/ui/review-page";

export const metadata: Metadata = {
  title: "Review queue",
};

export default function AdminReviewPage() {
  return (
    <Suspense fallback={<ReviewPageSkeleton />}>
      <ReviewPage />
    </Suspense>
  );
}