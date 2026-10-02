import type { ReviewStatus } from "@/entities/session/types";
import { t } from "@/shared/i18n";

export interface ReviewQueueView {
  items: ReviewItem[];
  totalCount: number;
  pendingCount: number;
  approvedCount: number;
  rejectedCount: number;
  filter: ReviewStatus | "all";
  sort: "created" | "priority" | "type";
}

export interface ReviewItem {
  id: string;
  type: string;
  title: string;
  description: string;
  status: ReviewStatus;
  priority: string;
  submittedBy: string;
  submittedAt: string;
  reviewedBy: string | null;
  reviewedAt: string | null;
  reviewNotes: string | null;
  businessId: string;
  businessName: string;
  relatedEntityId: string | null;
}

export function emptyReviewQueue(): ReviewQueueView {
  return {
    items: [],
    totalCount: 0,
    pendingCount: 0,
    approvedCount: 0,
    rejectedCount: 0,
    filter: "pending",
    sort: "created",
  };
}

export function reviewStatusLabel(status: ReviewStatus): string {
  return t(`review.status.${status}`);
}
