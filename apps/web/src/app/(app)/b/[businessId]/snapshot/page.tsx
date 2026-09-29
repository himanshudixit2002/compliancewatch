import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { SnapshotView, businessHeaderLinks, getSnapshotPage } from "@/features/business";
import { requireScreenSession } from "@/server/dal";
import { hrefFor, screenById } from "@/shared/config/screens";
import { isUuid } from "@/shared/lib/identifiers";
import { withQuery } from "@/shared/lib/url";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.business.snapshot");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ businessId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function BusinessSnapshotPage({ params, searchParams }: Props) {
  const { businessId } = await params;
  const session = await requireScreenSession(SCREEN, { businessId });
  const query = await searchParams;
  const node = first(query.node);
  const fy = first(query.fy);
  if (!isUuid(businessId) || (node !== undefined && !isUuid(node))) notFound();
  const page = await getSnapshotPage(session, businessId, {
    ...(node === undefined ? {} : { node }),
    ...(fy === undefined ? {} : { fy }),
  });
  if (!page.ok) {
    if (page.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={page.error} />;
  }
  const view = page.value;
  const pageHref = hrefFor(SCREEN, { businessId });
  return (
    <SnapshotView
      title={SCREEN.title}
      view={view}
      header={businessHeaderLinks("owner.business.snapshot", session, businessId, view.header.name)}
      pageHref={pageHref}
      nodeHref={(nodeId) => withQuery(pageHref, { node: nodeId, fy: view.fy })}
    />
  );
}
