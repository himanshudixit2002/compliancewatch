import type { Metadata } from "next";
import { VersionsView, getVersionList, readListFilter } from "@/features/rule-versions";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";
import { todayKey } from "@/shared/lib/dates";

const SCREEN = screenById("admin.rulebook.versions");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function RuleVersionsPage({ searchParams }: Props) {
  await requireScreenSession(SCREEN);
  const read = readListFilter(await searchParams, todayKey());
  const list = Object.keys(read.invalid).length > 0 ? null : await getVersionList(read.filter);
  return (
    <VersionsView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.rulebook.versions")}
      pageHref={hrefFor(SCREEN)}
      read={read}
      view={list?.ok === true ? list.value : null}
      {...(list !== null && !list.ok ? { error: list.error } : {})}
    />
  );
}
