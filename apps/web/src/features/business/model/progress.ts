import type { Onboarding } from "@/entities/business/types";
import { t } from "@/shared/i18n";

/**
 * Onboarding progress as the business API counts it: `answered` of `total` questions for the
 * business and its registrations, in the financial year per-year questions are asked for. An
 * unsure answer does not count as answered (the checklist asks it again). The percentage is for a
 * progress bar's value; the text is what the bar says.
 */
export interface OnboardingProgress {
  answered: number;
  total: number;
  /** 0 to 100, whole. */
  percent: number;
  text: string;
  complete: boolean;
}

export function onboardingProgress(onboarding: Onboarding): OnboardingProgress {
  const total = Math.max(0, onboarding.total);
  const answered = Math.min(Math.max(0, onboarding.answered), total);
  const percent = total === 0 ? 100 : Math.round((answered / total) * 100);
  return {
    answered,
    total,
    percent,
    text: t("business.progress", { answered, total }),
    complete: onboarding.complete,
  };
}
