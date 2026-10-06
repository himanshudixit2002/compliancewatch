import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { businessFlags, businessHeaderLinks } from "@/features/business";
import {
  ObligationsView,
  getObligationList,
  readListFilter,
  statusFilterOptions,
} from "@/features/obligations";
import { requireScreenSession } from "@/server/dal";
import { hrefFor, screenById } from "@/shared/config/screens";
import { isUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.obligations");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ businessId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function ObligationsPage({ params, searchParams }: Props) {
  const { businessId } = await params;
  const session = await requireScreenSession(SCREEN, { businessId });
  if (!isUuid(businessId)) notFound();
  const list = await getObligationList(session, businessId, readListFilter(await searchParams));
  if (!list.ok) {
    if (list.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={list.error} />;
  }
  return (
    <ObligationsView
      title={SCREEN.title}
      view={list.value}
      header={businessHeaderLinks(
        "owner.obligations",
        session,
        businessId,
        list.value.business.name,
        await businessFlags(session),
      )}
      pageHref={hrefFor(SCREEN, { businessId })}
      statusOptions={statusFilterOptions()}
      severalNodes={list.value.nodes > 1}
    />
  );
}
