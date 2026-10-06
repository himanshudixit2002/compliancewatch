import type { Metadata } from "next";
import { PromptsView, editNote, getPrompts } from "@/features/llm-registry";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.llm.prompts");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function PromptsPage() {
  await requireScreenSession(SCREEN);
  const rows = await getPrompts();
  if (!rows.ok) return <ServiceError heading={SCREEN.title} error={rows.error} />;
  return (
    <PromptsView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.llm.prompts")}
      rows={rows.value}
      note={editNote()}
    />
  );
}
