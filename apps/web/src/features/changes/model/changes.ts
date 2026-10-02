import type { RuleVersion, RelationSummary } from "@/entities/rulebook/types";
import { t } from "@/shared/i18n";

export interface ChangeView {
  changes: ChangeItem[];
  totalCount: number;
  applicableCount: number;
  pendingReviewCount: number;
  period: string;
}

export interface ChangeItem {
  id: string;
  ruleId: string;
  title: string;
  regulator: string;
  effectiveDate: string;
  publishedAt: string;
  applicability: "applies" | "does_not_apply" | "pending" | "unknown";
  confidence: number | null;
  reviewStatus: "published" | "in_review" | "rejected" | "draft";
  categories: string[];
  supersedes: string | null;
  summary: string;
  createdAt: string;
  updatedAt: string;
}

export function emptyChanges(): ChangeView {
  return {
    changes: [],
    totalCount: 0,
    applicableCount: 0,
    pendingReviewCount: 0,
    period: "",
  };
}

export function changeApplicabilityLabel(applicability: ChangeItem["applicability"]): string {
  return t(`changes.applicability.${applicability}`);
}

export function changeReviewLabel(review: ChangeItem["reviewStatus"]): string {
  return t(`changes.review.${review}`);
}

export function formatEffectiveDate(date: string): string {
  return new Date(date).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function changeSummary(summary: string): string {
  if (!summary || summary.length <= 200) return summary;
  return summary.slice(0, 200) + "...";
}
