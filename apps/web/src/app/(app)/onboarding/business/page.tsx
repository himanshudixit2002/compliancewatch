import type { Metadata } from "next";
import { BUSINESS_FORM_FIELDS, BusinessStep, createBusiness } from "@/features/business";
import { getConsentStep } from "@/features/consents";
import { IdempotencyKeyInput } from "@/server/api/idempotency";
import { requireScreenSession } from "@/server/dal";
import { hrefFor, screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.onboarding.business");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function OnboardingBusinessPage() {
  const session = await requireScreenSession(SCREEN);
  const consents = await getConsentStep(session);
  if (!consents.ok) return <ServiceError heading={SCREEN.title} error={consents.error} />;
  return (
    <BusinessStep
      title={SCREEN.title}
      consentAccepted={consents.value.accepted}
      consentHref={hrefFor(screenById("owner.onboarding"))}
      action={createBusiness}
      idempotencyInput={<IdempotencyKeyInput />}
      fields={BUSINESS_FORM_FIELDS}
      againHref={hrefFor(SCREEN)}
    />
  );
}
