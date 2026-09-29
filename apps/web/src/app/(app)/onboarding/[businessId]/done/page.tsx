import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  ANSWER_FIELDS,
  DoneSummary,
  getDoneSummary,
  revisitUnsure,
  summaryViewedEvent,
} from "@/features/business";
import { track } from "@/server/analytics";
import { requireScreenSession } from "@/server/dal";
import { hrefFor, screenById } from "@/shared/config/screens";
import { isUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.onboarding.done");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ businessId: string }>;
}

export default async function OnboardingDonePage({ params }: Props) {
  const { businessId } = await params;
  const session = await requireScreenSession(SCREEN, { businessId });
  if (!isUuid(businessId)) notFound();
  const summary = await getDoneSummary(session, businessId);
  if (!summary.ok) {
    if (summary.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={summary.error} />;
  }
  await track(session, summaryViewedEvent(summary.value));
  return (
    <DoneSummary
      title={SCREEN.title}
      view={summary.value}
      revisitAction={revisitUnsure}
      businessIdField={ANSWER_FIELDS.businessId}
      questionsHref={hrefFor(screenById("owner.onboarding.questions"), { businessId })}
      businessHref={hrefFor(screenById("owner.business"), { businessId })}
    />
  );
}
