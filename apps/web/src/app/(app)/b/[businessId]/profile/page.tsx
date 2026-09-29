import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  BusinessProfile,
  LOCATION_FIELDS,
  addLocation,
  businessHeaderLinks,
  getProfilePage,
} from "@/features/business";
import { requireScreenSession } from "@/server/dal";
import { can } from "@/shared/config/permissions";
import { hrefFor, screenById } from "@/shared/config/screens";
import { isUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.business.profile");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ businessId: string }>;
}

export default async function BusinessProfilePage({ params }: Props) {
  const { businessId } = await params;
  const session = await requireScreenSession(SCREEN, { businessId });
  if (!isUuid(businessId)) notFound();
  const business = await getProfilePage(session, businessId);
  if (!business.ok) {
    if (business.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={business.error} />;
  }
  const attributes = hrefFor(screenById("owner.business.attributes"), { businessId });
  const snapshot = hrefFor(screenById("owner.business.snapshot"), { businessId });
  const nodeIds = [business.value.id, ...business.value.registrations.map((node) => node.id)];
  const nodeLinks = Object.fromEntries(
    nodeIds.map((id) => [
      id,
      { attributes: `${attributes}?node=${id}`, snapshot: `${snapshot}?node=${id}` },
    ]),
  );
  return (
    <BusinessProfile
      title={SCREEN.title}
      business={business.value}
      header={businessHeaderLinks(
        "owner.business.profile",
        session,
        businessId,
        business.value.name,
      )}
      nodeLinks={nodeLinks}
      locationAction={can(session, "profile.edit") ? addLocation : null}
      locationFields={LOCATION_FIELDS}
    />
  );
}
