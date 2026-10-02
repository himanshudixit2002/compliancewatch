import type { Metadata } from "next";
import { BUSINESS_FORM_FIELDS, BusinessStep, createBusiness } from "@/features/business";
import { IdempotencyKeyInput } from "@/server/api/idempotency";
import { requireScreenSession } from "@/server/dal";
import { onboardingGate } from "@/server/legal";
import { hasRequiredConsents } from "@/server/required-consents";
import { hrefFor, screenById } from "@/shared/config/screens";
import { OnboardingClosed } from "@/shared/ui/onboarding-closed";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.onboarding.business");
const LEGAL = screenById("system.legal");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function OnboardingBusinessPage() {
  const session = await requireScreenSession(SCREEN);
  const gate = onboardingGate();
  if (gate.closed) {
    return (
      <OnboardingClosed
        title={SCREEN.title}
        step="business"
        documents={gate.drafts}
        documentHref={(doc) => hrefFor(LEGAL, { doc })}
      />
    );
  }
  // The same check createBusiness makes again before any profile call.
  const consents = await hasRequiredConsents(session);
  if (!consents.ok) return <ServiceError heading={SCREEN.title} error={consents.error} />;
  return (
    <BusinessStep
      title={SCREEN.title}
      consentAccepted={consents.value}
      consentHref={hrefFor(screenById("owner.onboarding"))}
      action={createBusiness}
      idempotencyInput={<IdempotencyKeyInput />}
      fields={BUSINESS_FORM_FIELDS}
      againHref={hrefFor(SCREEN)}
    />
  );
}
