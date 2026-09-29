import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  BusinessHome,
  businessHeaderLinks,
  getBusinessHome,
  laterScreens,
} from "@/features/business";
import { requireScreenSession } from "@/server/dal";
import { hrefFor, isVisibleTo, screenById } from "@/shared/config/screens";
import { isUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.business");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ businessId: string }>;
}

export default async function BusinessHomePage({ params }: Props) {
  const { businessId } = await params;
  const session = await requireScreenSession(SCREEN, { businessId });
  if (!isUuid(businessId)) notFound();
  const home = await getBusinessHome(session, businessId);
  if (!home.ok) {
    if (home.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={home.error} />;
  }
  const at = (id: Parameters<typeof screenById>[0]) => hrefFor(screenById(id), { businessId });
  const onboards = isVisibleTo(
    screenById("owner.onboarding.questions"),
    session.roles,
    session.tenantKind,
  );
  return (
    <BusinessHome
      view={home.value}
      header={businessHeaderLinks("owner.business", session, businessId, home.value.header.name)}
      links={{
        profile: at("owner.business.profile"),
        attributes: at("owner.business.attributes"),
        snapshot: at("owner.business.snapshot"),
        reviewTasks: at("owner.business.review-tasks"),
        questions: onboards ? at("owner.onboarding.questions") : null,
        done: onboards ? at("owner.onboarding.done") : null,
      }}
      later={laterScreens(session, businessId)}
    />
  );
}
