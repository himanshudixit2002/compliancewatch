import type { Metadata } from "next";
import { TemplatesView, getTemplates } from "@/features/notifications";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.notifications.templates");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function MessageTemplatesPage() {
  await requireScreenSession(SCREEN);
  const rows = await getTemplates();
  if (!rows.ok) return <ServiceError heading={SCREEN.title} error={rows.error} />;
  return (
    <TemplatesView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.notifications.templates")}
      rows={rows.value}
    />
  );
}
