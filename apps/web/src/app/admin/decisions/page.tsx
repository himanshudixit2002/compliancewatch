import type { Metadata } from "next";
import {
  DecisionsView,
  getReviewItems,
  readDecisionLookup,
  resolveReviewItem,
} from "@/features/decision-review";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.decisions");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function DecisionsPage({ searchParams }: Props) {
  const session = await requireScreenSession(SCREEN);
  const lookup = readDecisionLookup(await searchParams);
  const read = lookup.kind === "ok" ? await getReviewItems(session, lookup) : null;
  return (
    <DecisionsView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.decisions")}
      pageHref={hrefFor(SCREEN)}
      lookup={lookup}
      view={read?.ok === true ? read.value : null}
      {...(read !== null && !read.ok ? { error: read.error } : {})}
      resolve={resolveReviewItem}
    />
  );
}
