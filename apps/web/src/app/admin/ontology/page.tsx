import type { Metadata } from "next";
import { OntologyView, getOntologyBrowser, usageNote } from "@/features/admin-ontology";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.ontology");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function OntologyPage() {
  await requireScreenSession(SCREEN);
  const view = await getOntologyBrowser();
  if (!view.ok) return <ServiceError heading={SCREEN.title} error={view.error} />;
  return (
    <OntologyView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.ontology")}
      view={view.value}
      usage={usageNote()}
    />
  );
}
