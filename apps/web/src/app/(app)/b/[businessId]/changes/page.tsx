import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { businessFlags, businessHeaderLinks } from "@/features/business";
import { ChangesView, getChanges, readFeedCursor } from "@/features/changes";
import { requireScreenSession } from "@/server/dal";
import { screenById } from "@/shared/config/screens";
import { isUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.changes");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ businessId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function ChangesPage({ params, searchParams }: Props) {
  const { businessId } = await params;
  const session = await requireScreenSession(SCREEN, { businessId });
  if (!isUuid(businessId)) notFound();
  const changes = await getChanges(
    session,
    businessId,
    readFeedCursor((await searchParams).cursor),
  );
  if (!changes.ok) {
    if (changes.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={changes.error} />;
  }
  return (
    <ChangesView
      title={SCREEN.title}
      view={changes.value}
      header={businessHeaderLinks(
        "owner.changes",
        session,
        businessId,
        changes.value.business.name,
        await businessFlags(session),
      )}
    />
  );
}
