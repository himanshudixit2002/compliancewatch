/** Onboarding questions answered so far for the business still being set up. */
export interface OnboardingStatus {
  businessName: string;
  answered: number;
  total: number;
}

/** The owner's home: counts across their businesses and any onboarding still open. */
export interface OwnerHomeSummary {
  businessesCount: number;
  pendingReview: number;
  openObligations: number;
  upcomingDeadlines: number;
  recentChanges: number;
  /** Set while a business's onboarding is incomplete. */
  onboarding: OnboardingStatus | null;
}

export function emptyOwnerHome(): OwnerHomeSummary {
  return {
    businessesCount: 0,
    pendingReview: 0,
    openObligations: 0,
    upcomingDeadlines: 0,
    recentChanges: 0,
    onboarding: null,
  };
}

export function hasBusinesses(summary: OwnerHomeSummary): boolean {
  return summary.businessesCount > 0;
}

/** True when there is onboarding left to finish (answered below total). */
export function onboardingOpen(summary: OwnerHomeSummary): boolean {
  const onboarding = summary.onboarding;
  return onboarding !== null && onboarding.answered < onboarding.total;
}
