import type { Metadata } from "next";
import {
  QueueView,
  claimFromQueue,
  getQueuePage,
  openSeedTasks,
  readQueueFilter,
  samplingNote,
} from "@/features/review-tasks";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.review");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function ReviewQueuePage({ searchParams }: Props) {
  const session = await requireScreenSession(SCREEN);
  const filter = readQueueFilter(await searchParams);
  const page = await getQueuePage(session, filter);
  return (
    <QueueView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.review")}
      filter={filter}
      view={page.queue.ok ? page.queue.value : null}
      {...(page.queue.ok ? {} : { error: page.queue.error })}
      strip={page.strip.ok ? page.strip.value : null}
      {...(page.strip.ok ? {} : { stripError: page.strip.error })}
      regulators={page.regulators}
      access={page.access}
      claim={page.access.allowed ? claimFromQueue : null}
      openSeedTasks={page.access.allowed ? openSeedTasks : null}
      sampling={samplingNote(session.roles)}
    />
  );
}
