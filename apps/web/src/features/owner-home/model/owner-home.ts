import type { OnboardingProgress } from "@/entities/business/types";
import { t } from "@/shared/i18n";

export interface OwnerHomeView {
  hasBusinesses: boolean;
  pendingReview: number;
  openObligations: number;
  upcomingDeadlines: number;
  recentChanges: number;
  onboardingProgress?: OnboardingProgress;
  businessesCount: number;
}

export function emptyOwnerHome(): OwnerHomeView {
  return {
    hasBusinesses: false,
    pendingReview: 0,
    openObligations: 0,
    upcomingDeadlines: 0,
    recentChanges: 0,
    businessesCount: 0,
  };
}
