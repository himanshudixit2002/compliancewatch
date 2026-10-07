import type { Metadata } from "next";
import { StatsView, getStatsPage } from "@/features/review-tasks";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.review.stats");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function ReviewStatsPage() {
  await requireScreenSession(SCREEN);
  const stats = await getStatsPage();
  return (
    <StatsView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.review.stats")}
      view={stats.ok ? stats.value : null}
      {...(stats.ok ? {} : { error: stats.error })}
      queueHref={hrefFor(screenById("admin.review"))}
    />
  );
}
