import type { Metadata } from "next";
import { EntityQueueView, getEntityQueue, readQueue } from "@/features/entity-review";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.rulebook.entities");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function EntityReviewPage({ searchParams }: Props) {
  await requireScreenSession(SCREEN);
  const read = readQueue(await searchParams);
  const queue = read.kind === "ok" ? await getEntityQueue(read.filter) : null;
  return (
    <EntityQueueView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.rulebook.entities")}
      pageHref={hrefFor(SCREEN)}
      read={read}
      view={queue?.ok === true ? queue.value : null}
      {...(queue !== null && !queue.ok ? { error: queue.error } : {})}
    />
  );
}
