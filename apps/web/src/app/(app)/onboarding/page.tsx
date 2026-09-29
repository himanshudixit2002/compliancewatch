import type { Metadata } from "next";
import {
  ConsentStep,
  WHATSAPP_NUMBER_FIELD,
  getConsentStep,
  recordConsents,
} from "@/features/consents";
import { requireScreenSession } from "@/server/dal";
import { hrefFor, screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.onboarding");
const LEGAL = screenById("system.legal");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function OnboardingConsentPage() {
  const session = await requireScreenSession(SCREEN);
  const step = await getConsentStep(session);
  if (!step.ok) return <ServiceError heading={SCREEN.title} error={step.error} />;
  return (
    <ConsentStep
      title={SCREEN.title}
      view={step.value}
      action={recordConsents}
      continueHref={hrefFor(screenById("owner.onboarding.business"))}
      documentHref={(doc) => hrefFor(LEGAL, { doc })}
      whatsappField={WHATSAPP_NUMBER_FIELD}
    />
  );
}
