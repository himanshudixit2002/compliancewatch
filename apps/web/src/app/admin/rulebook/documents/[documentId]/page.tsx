import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  DocumentView,
  getDocumentView,
  parseHighlightRequest,
  type SearchParams,
} from "@/features/rulebook-documents";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { isHexUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.rulebook.document");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ documentId: string }>;
  searchParams: Promise<SearchParams>;
}

// No loading.tsx: an unknown or malformed id answers a real 404 (a loading boundary would
// stream it with status 200), and the document is a cached global read.
export default async function DocumentPage({ params, searchParams }: Props) {
  const { documentId } = await params;
  await requireScreenSession(SCREEN, { documentId });
  if (!isHexUuid(documentId)) notFound();
  const id = documentId.toLowerCase();
  const view = await getDocumentView(id, parseHighlightRequest(await searchParams));
  if (!view.ok) {
    if (view.error.kind === "not_found" || view.error.kind === "validation") notFound();
    return <ServiceError heading={SCREEN.title} error={view.error} />;
  }
  const crumbs = breadcrumbsFor("admin.rulebook.document", { documentId: id }).map((crumb) =>
    crumb.id === SCREEN.id ? { ...crumb, label: view.value.externalRef } : crumb,
  );
  return <DocumentView view={view.value} crumbs={crumbs} />;
}
