import type { Metadata } from "next";
import { SourcesError, SourcesView, addSourceNote, getSourcesPage } from "@/features/admin-sources";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { can } from "@/shared/config/permissions";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.sources");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function SourcesPage() {
  const session = await requireScreenSession(SCREEN);
  const crumbs = breadcrumbsFor("admin.sources");
  const page = await getSourcesPage();
  if (!page.ok) return <SourcesError title={SCREEN.title} crumbs={crumbs} error={page.error} />;
  return (
    <SourcesView
      title={SCREEN.title}
      crumbs={crumbs}
      view={page.value}
      addNote={can(session, "admin.sources.write") ? addSourceNote() : null}
    />
  );
}
