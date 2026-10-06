import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DocumentView, getDocumentPage, retryDocument } from "@/features/admin-pipeline";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { isHexUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.pipeline.document");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ documentId: string }>;
}

export default async function StoredDocumentPage({ params }: Props) {
  const { documentId } = await params;
  const session = await requireScreenSession(SCREEN, { documentId });
  if (!isHexUuid(documentId)) notFound();
  const id = documentId.toLowerCase();
  const page = await getDocumentPage(session, id);
  if (!page.ok) return <ServiceError heading={SCREEN.title} error={page.error} />;
  if (page.value === null) notFound();
  const { view, access, retryKey } = page.value;
  const crumbs = breadcrumbsFor("admin.pipeline.document", { documentId: id }).map((crumb) =>
    crumb.id === SCREEN.id ? { ...crumb, label: view.title } : crumb,
  );
  return (
    <DocumentView
      title={view.title}
      crumbs={crumbs}
      view={view}
      access={access}
      retryAction={access.allowed ? retryDocument.bind(null, id) : null}
      retryKey={retryKey}
    />
  );
}
