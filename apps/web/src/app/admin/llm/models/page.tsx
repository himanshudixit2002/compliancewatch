import type { Metadata } from "next";
import { ModelsView, editNote, getModels } from "@/features/llm-registry";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.llm.models");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function ModelRoutesPage() {
  await requireScreenSession(SCREEN);
  const rows = await getModels();
  if (!rows.ok) return <ServiceError heading={SCREEN.title} error={rows.error} />;
  return (
    <ModelsView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.llm.models")}
      rows={rows.value}
      note={editNote()}
    />
  );
}
