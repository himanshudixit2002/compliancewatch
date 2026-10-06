import type { Metadata } from "next";
import { ReviewTasksView, getNodeReview, readLookup } from "@/features/profile-review-tasks";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.profiles.review-tasks");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function ProfileReviewTasksPage({ searchParams }: Props) {
  const session = await requireScreenSession(SCREEN);
  const lookup = readLookup(await searchParams);
  const read = lookup.kind === "ok" ? await getNodeReview(session, lookup) : null;
  return (
    <ReviewTasksView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.profiles.review-tasks")}
      pageHref={hrefFor(SCREEN)}
      lookup={lookup}
      view={read?.ok === true ? read.value : null}
      notFound={read?.ok === true && read.value === null}
      {...(read !== null && !read.ok ? { error: read.error } : {})}
    />
  );
}
