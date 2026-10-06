import type { Metadata } from "next";
import { RulesView, getRules } from "@/features/rulebook-rules";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.rulebook.rules");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function RulesPage() {
  await requireScreenSession(SCREEN);
  const rows = await getRules();
  if (!rows.ok) return <ServiceError heading={SCREEN.title} error={rows.error} />;
  return (
    <RulesView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.rulebook.rules")}
      rows={rows.value}
    />
  );
}
