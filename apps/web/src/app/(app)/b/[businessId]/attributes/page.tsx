import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  ANSWER_FIELDS,
  AttributesView,
  businessFlags,
  businessHeaderLinks,
  getAttributesPage,
  isAttributeKey,
  saveAttribute,
} from "@/features/business";
import { requireScreenSession } from "@/server/dal";
import { can } from "@/shared/config/permissions";
import { hrefFor, screenById } from "@/shared/config/screens";
import { isUuid } from "@/shared/lib/identifiers";
import { withQuery } from "@/shared/lib/url";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.business.attributes");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ businessId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function BusinessAttributesPage({ params, searchParams }: Props) {
  const { businessId } = await params;
  const session = await requireScreenSession(SCREEN, { businessId });
  const query = await searchParams;
  const node = first(query.node);
  const edit = first(query.edit);
  if (!isUuid(businessId) || (node !== undefined && !isUuid(node))) notFound();
  const page = await getAttributesPage(session, businessId, {
    ...(node === undefined ? {} : { node }),
    ...(first(query.fy) === undefined ? {} : { fy: first(query.fy) }),
    ...(edit !== undefined && isAttributeKey(edit) ? { edit } : {}),
    canEdit: can(session, "profile.edit"),
  });
  if (!page.ok) {
    if (page.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={page.error} />;
  }
  const view = page.value;
  const pageHref = hrefFor(SCREEN, { businessId });
  return (
    <AttributesView
      title={SCREEN.title}
      view={view}
      header={businessHeaderLinks(
        "owner.business.attributes",
        session,
        businessId,
        view.header.name,
        await businessFlags(session),
      )}
      pageHref={pageHref}
      nodeHref={(nodeId) => withQuery(pageHref, { node: nodeId, fy: view.fy })}
      closeHref={withQuery(pageHref, { node: view.node.id, fy: view.fy })}
      saveAction={saveAttribute}
      fields={ANSWER_FIELDS}
    />
  );
}
