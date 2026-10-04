import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { EntityView, getEntityPage } from "@/features/rulebook-entities";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";
import { isDateKey } from "@/shared/lib/dates";
import { isHexUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.rulebook.canonical.entity");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ entityId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function CanonicalEntityPage({ params, searchParams }: Props) {
  const { entityId } = await params;
  await requireScreenSession(SCREEN, { entityId });
  if (!isHexUuid(entityId)) notFound();
  const id = entityId.toLowerCase();
  const raw = (await searchParams).as_of;
  const asOfText = (Array.isArray(raw) ? raw[0] : raw)?.trim() ?? "";
  const asOf = asOfText !== "" && isDateKey(asOfText) ? asOfText : null;
  const page = await getEntityPage(id, asOf);
  if (!page.ok) {
    if (page.error.kind === "not_found" || page.error.kind === "validation") notFound();
    return <ServiceError heading={SCREEN.title} error={page.error} />;
  }
  const crumbs = breadcrumbsFor("admin.rulebook.canonical.entity", { entityId: id }).map((crumb) =>
    crumb.id === SCREEN.id ? { ...crumb, label: page.value.entity.canonicalName } : crumb,
  );
  return (
    <EntityView
      view={page.value}
      crumbs={crumbs}
      pageHref={hrefFor(SCREEN, { entityId: id })}
      {...(asOfText !== "" && asOf === null ? { invalidAsOf: asOfText } : {})}
    />
  );
}
