import type { Route } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { Banner, Button, KeyValue } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { BusinessHeader } from "../model/business-pages";
import { BusinessPageHeader, type BusinessPageHeaderProps } from "./business-page-header";
import { LocationForm, type LocationAction } from "./location-form";
import { RegistrationForm, type RegistrationAction } from "./registration-form";

export interface NodeLinks {
  attributes: string;
  snapshot: string;
}

export interface BusinessProfileProps {
  title: string;
  business: BusinessHeader;
  header: Omit<BusinessPageHeaderProps, "title" | "description">;
  /** The attributes and snapshot pages of a node, by its id. */
  nodeLinks: Readonly<Record<string, NodeLinks>>;
  /** Null for a role that may not change the profile (a compliance lead). */
  locationAction: LocationAction | null;
  locationFields: { businessId: string; registrationId: string; label: string; name: string };
  /**
   * Adding a GSTIN: the form, or the way to the consent step while the required consents are
   * not on file; null for a role that may not change the profile.
   */
  registration: RegistrationSection | null;
  /** The business step, for a GSTIN of another PAN; null for a role that does not add one. */
  addBusinessHref: string | null;
  /** True for a CA firm, whose businesses are its clients. */
  clients?: boolean;
}

export type RegistrationSection =
  | {
      status: "form";
      action: RegistrationAction;
      /** The hidden Idempotency-Key input the page rendered for this form. */
      idempotencyInput: ReactNode;
      fields: { businessId: string; gstin: string; name: string };
      /** This page again, loaded afresh for another GSTIN. */
      againHref: string;
    }
  | { status: "consent-first"; consentHref: string };

function NodeLinksLine({ links }: { links: NodeLinks | undefined }) {
  if (links === undefined) return null;
  return (
    <p className="text-sm">
      <Link href={links.attributes as Route} className="text-primary underline">
        {t("business.tile.attributes")}
      </Link>
      {" · "}
      <Link href={links.snapshot as Route} className="text-primary underline">
        {t("business.tile.snapshot")}
      </Link>
    </p>
  );
}

function AddRegistration({
  business,
  section,
  addBusinessHref,
  clients,
}: {
  business: BusinessHeader;
  section: RegistrationSection;
  addBusinessHref: string | null;
  clients: boolean;
}) {
  return (
    <section aria-labelledby="profile-add-registration" className="flex flex-col gap-3">
      <h2 id="profile-add-registration" className="text-lg font-semibold text-fg">
        {t("registration.title")}
      </h2>
      <p className="text-sm text-fg-muted">
        {t("registration.intro")}{" "}
        {addBusinessHref === null ? null : (
          <Link href={addBusinessHref as Route} className="text-primary underline">
            {clients ? t("business.addClient") : t("business.addBusiness")}
          </Link>
        )}
      </p>
      {section.status === "form" ? (
        <RegistrationForm
          action={section.action}
          businessId={business.id}
          businessName={business.name}
          pan={business.pan}
          idempotencyInput={section.idempotencyInput}
          fields={section.fields}
          againHref={section.againHref}
        />
      ) : (
        <Banner
          tone="warning"
          title={t("businessStep.consentFirstTitle")}
          data-slot="registration-consent-first"
          action={
            <Button asChild variant="secondary" size="sm">
              <Link href={section.consentHref as Route}>{t("businessStep.consentFirstLink")}</Link>
            </Button>
          }
        >
          {t("businessStep.consentFirst")}
        </Banner>
      )}
    </section>
  );
}

/**
 * The business's hierarchy: the legal entity by its PAN, then each GSTIN registration, each with
 * links to its attributes and snapshot and, for a role that may change the profile, a form to add
 * a location under it, and a form to add another GSTIN of the business (once the required
 * consents are on file). Locations are not listed: no route lists a registration's children yet.
 */
export function BusinessProfile({
  title,
  business,
  header,
  nodeLinks,
  locationAction,
  locationFields,
  registration,
  addBusinessHref,
  clients = false,
}: BusinessProfileProps) {
  return (
    <div data-slot="business-profile" className="flex max-w-4xl flex-col gap-6">
      <BusinessPageHeader
        {...header}
        title={title}
        description={t("business.pageIntro", { name: business.name, pan: business.pan })}
      />
      <section aria-labelledby="profile-entity" className="flex flex-col gap-3">
        <h2 id="profile-entity" className="text-lg font-semibold text-fg">
          {t("business.level.entity")}
        </h2>
        <KeyValue
          items={[
            { key: "name", label: t("business.name"), value: business.name },
            { key: "pan", label: t("prefill.pan"), value: business.pan },
            { key: "version", label: t("business.version"), value: String(business.version) },
            { key: "updated", label: t("business.updatedAt"), value: business.updatedAt },
          ]}
        />
        <NodeLinksLine links={nodeLinks[business.id]} />
      </section>
      <section aria-labelledby="profile-registrations" className="flex flex-col gap-4">
        <h2 id="profile-registrations" className="text-lg font-semibold text-fg">
          {t("business.registrations")}
        </h2>
        {business.registrations.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("business.noRegistrations")}</p>
        ) : null}
        {business.registrations.map((registration) => (
          <article
            key={registration.id}
            aria-labelledby={`registration-${registration.id}`}
            className="flex flex-col gap-3 rounded-lg border border-line p-4"
          >
            <h3 id={`registration-${registration.id}`} className="font-semibold text-fg">
              {registration.key}
            </h3>
            <KeyValue
              items={[
                { key: "name", label: t("business.name"), value: registration.name },
                {
                  key: "version",
                  label: t("business.version"),
                  value: String(registration.version),
                },
              ]}
            />
            <NodeLinksLine links={nodeLinks[registration.id]} />
            {locationAction === null ? null : (
              <div className="flex flex-col gap-2 border-t border-line pt-3">
                <h4 className="text-sm font-semibold text-fg">{t("location.title")}</h4>
                <LocationForm
                  action={locationAction}
                  businessId={business.id}
                  registrationId={registration.id}
                  gstin={registration.key}
                  fields={locationFields}
                />
              </div>
            )}
          </article>
        ))}
        <p className="text-sm text-fg-muted">{t("location.notListed")}</p>
      </section>
      {registration === null ? null : (
        <AddRegistration
          business={business}
          section={registration}
          addBusinessHref={addBusinessHref}
          clients={clients}
        />
      )}
    </div>
  );
}
