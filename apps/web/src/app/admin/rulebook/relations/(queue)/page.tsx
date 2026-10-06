import type { Metadata } from "next";
import { CandidatesView, getCandidateQueue, readCandidateQueue } from "@/features/relation-review";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.rulebook.relations");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function RelationCandidatesPage({ searchParams }: Props) {
  await requireScreenSession(SCREEN);
  const read = readCandidateQueue(await searchParams);
  const queue = read.kind === "ok" ? await getCandidateQueue(read.filter) : null;
  return (
    <CandidatesView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.rulebook.relations")}
      pageHref={hrefFor(SCREEN)}
      read={read}
      view={queue?.ok === true ? queue.value : null}
      {...(queue !== null && !queue.ok ? { error: queue.error } : {})}
    />
  );
}
