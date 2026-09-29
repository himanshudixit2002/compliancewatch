import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  BusinessProfile,
  LOCATION_FIELDS,
  REGISTRATION_FIELDS,
  addLocation,
  addRegistration,
  businessHeaderLinks,
  getProfilePage,
  type RegistrationSection,
} from "@/features/business";
import { IdempotencyKeyInput } from "@/server/api/idempotency";
import { requireScreenSession } from "@/server/dal";
import { hasRequiredConsents } from "@/server/required-consents";
import { can } from "@/shared/config/permissions";
import { hrefFor, isVisibleTo, screenById } from "@/shared/config/screens";
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
  const edits = can(session, "profile.edit");
  const [business, consents] = await Promise.all([
    getProfilePage(session, businessId),
    // Adding a GSTIN needs the required consents, as creating a business does; addRegistration
    // checks again. When they cannot be read the form is offered and the action reports why.
    edits ? hasRequiredConsents(session) : null,
  ]);
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
  const registration: RegistrationSection | null = !edits
    ? null
    : consents?.ok === true && !consents.value
      ? { status: "consent-first", consentHref: hrefFor(screenById("owner.onboarding")) }
      : {
          status: "form",
          action: addRegistration,
          idempotencyInput: <IdempotencyKeyInput />,
          fields: REGISTRATION_FIELDS,
          againHref: hrefFor(SCREEN, { businessId }),
        };
  const addsBusiness = screenById("owner.onboarding.business");
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
      locationAction={edits ? addLocation : null}
      locationFields={LOCATION_FIELDS}
      registration={registration}
      addBusinessHref={
        isVisibleTo(addsBusiness, session.roles, session.tenantKind) ? hrefFor(addsBusiness) : null
      }
      clients={session.tenantKind === "ca_firm"}
    />
  );
}
