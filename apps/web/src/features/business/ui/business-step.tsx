import type { Route } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { Banner, Button, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { OnboardingStepper } from "@/shared/ui/onboarding-stepper";
import { BusinessForm, type BusinessAction } from "./business-form";

export interface BusinessStepProps {
  title: string;
  /** True once the signed-in user has agreed to the required documents. */
  consentAccepted: boolean;
  /** The consent step, for a user who has not agreed yet. */
  consentHref: string;
  action: BusinessAction;
  idempotencyInput: ReactNode;
  fields: { gstin: string; name: string; registrationName: string };
  againHref: string;
}

/**
 * The second onboarding step: add a business by its GSTIN. The business API makes the business
 * from the PAN inside the GSTIN and pre-fills the registration from the GSTIN lookup. The step
 * asks for the consents first: the profile is processed on the strength of them, so without
 * them there is only the way back to the consent step.
 */
export function BusinessStep({
  title,
  consentAccepted,
  consentHref,
  action,
  idempotencyInput,
  fields,
  againHref,
}: BusinessStepProps) {
  return (
    <div data-slot="business-step" className="flex max-w-3xl flex-col gap-6">
      <OnboardingStepper current="business" />
      <PageHeader title={title} description={t("businessStep.intro")} />
      {consentAccepted ? (
        <BusinessForm
          action={action}
          idempotencyInput={idempotencyInput}
          fields={fields}
          againHref={againHref}
        />
      ) : (
        <Banner
          tone="warning"
          title={t("businessStep.consentFirstTitle")}
          data-slot="business-consent-first"
          action={
            <Button asChild variant="secondary" size="sm">
              <Link href={consentHref as Route}>{t("businessStep.consentFirstLink")}</Link>
            </Button>
          }
        >
          {t("businessStep.consentFirst")}
        </Banner>
      )}
    </div>
  );
}
