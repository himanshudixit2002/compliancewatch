import type { Metadata } from "next";
import { redirect } from "next/navigation";
import {
  BusinessDirectory,
  DIRECTORY_FIELDS,
  getDirectoryPage,
  searchBusinesses,
} from "@/features/business";
import { requireScreenSession } from "@/server/dal";
import { hrefFor, isVisibleTo, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.businesses");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function BusinessesPage() {
  const session = await requireScreenSession(SCREEN);
  const first = await getDirectoryPage(session, { q: "", page: 1 });
  if (!first.ok) return <ServiceError heading={SCREEN.title} error={first.error} />;
  const [only] = first.value.rows;
  // An owner with one business goes straight to it; a CA firm always sees its client list.
  if (
    session.tenantKind === "business" &&
    only !== undefined &&
    first.value.rows.length === 1 &&
    first.value.nextCursor === null
  ) {
    redirect(only.href);
  }
  const clients = session.tenantKind === "ca_firm";
  const onboarding = screenById("owner.onboarding.business");
  const onboards = isVisibleTo(onboarding, session.roles, session.tenantKind);
  return (
    <BusinessDirectory
      title={clients ? t("directory.clients.title") : SCREEN.title}
      audience={clients ? "clients" : "owner"}
      initial={first.value}
      action={searchBusinesses}
      fields={DIRECTORY_FIELDS}
      addHref={onboards ? hrefFor(onboarding) : null}
      startHref={onboards ? hrefFor(screenById("owner.onboarding")) : null}
    />
  );
}
