import type { Route } from "next";
import Link from "next/link";
import { KeyValue } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import type { BusinessHeader } from "../model/business-pages";
import { BusinessPageHeader, type BusinessPageHeaderProps } from "./business-page-header";
import { LocationForm, type LocationAction } from "./location-form";

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
}

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

/**
 * The business's hierarchy: the legal entity by its PAN, then each GSTIN registration, each with
 * links to its attributes and snapshot and, for a role that may change the profile, a form to add
 * a location under it. Locations are not listed: no route lists a registration's children yet.
 */
export function BusinessProfile({
  title,
  business,
  header,
  nodeLinks,
  locationAction,
  locationFields,
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
    </div>
  );
}
