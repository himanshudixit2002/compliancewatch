import type { Metadata } from "next";
import { ImpactView, initialValues, runDryRun } from "@/features/impact-explorer";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { isHexUuid } from "@/shared/lib/identifiers";

const SCREEN = screenById("admin.impact");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function ImpactExplorerPage({ searchParams }: Props) {
  await requireScreenSession(SCREEN);
  const named = (await searchParams).rule_version_id;
  const id =
    typeof named === "string" && isHexUuid(named.trim()) ? named.trim().toLowerCase() : null;
  return (
    <ImpactView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.impact")}
      action={runDryRun}
      initial={initialValues(id)}
    />
  );
}
