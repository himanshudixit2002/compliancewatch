import type { Metadata } from "next";
import { DocumentsOpenView, OPEN_FIELDS, openDocument } from "@/features/rulebook-documents";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.rulebook.documents");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

// No loading.tsx here: the page reads nothing, and a loading boundary on this segment would
// also wrap the viewer below it and stream its not-found answer with status 200.
export default async function DocumentsPage() {
  await requireScreenSession(SCREEN);
  return (
    <DocumentsOpenView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.rulebook.documents")}
      action={openDocument}
      field={OPEN_FIELDS.documentId}
    />
  );
}
