import { Stepper } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";

/**
 * The four onboarding steps, shared by the consent step (features/consents) and the business,
 * question and summary steps (features/business), which may not import each other.
 */
export const ONBOARDING_STEP_IDS = ["consent", "business", "questions", "done"] as const;

export type OnboardingStepId = (typeof ONBOARDING_STEP_IDS)[number];

export interface OnboardingStepperProps {
  current: OnboardingStepId;
  className?: string;
}

export function OnboardingStepper({ current, className }: OnboardingStepperProps) {
  const steps = ONBOARDING_STEP_IDS.map((id) => ({ id, label: t(`onboarding.step.${id}`) }));
  return (
    <Stepper
      steps={steps}
      current={ONBOARDING_STEP_IDS.indexOf(current)}
      label={t("onboarding.steps")}
      className={className}
    />
  );
}
