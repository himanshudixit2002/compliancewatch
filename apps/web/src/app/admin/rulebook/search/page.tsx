import type { Metadata } from "next";
import { SearchView, searchClauses } from "@/features/clause-search";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.rulebook.search");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function ClauseSearchPage() {
  await requireScreenSession(SCREEN);
  return (
    <SearchView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.rulebook.search")}
      action={searchClauses}
    />
  );
}
