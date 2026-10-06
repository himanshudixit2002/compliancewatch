import type { Metadata } from "next";
import {
  PipelineView,
  getPipelinePage,
  readPipelineQuery,
  requeueEvent,
} from "@/features/admin-pipeline";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.pipeline");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function PipelinePage({ searchParams }: Props) {
  const session = await requireScreenSession(SCREEN);
  const read = readPipelineQuery(await searchParams);
  const page = await getPipelinePage(session, read);
  return (
    <PipelineView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.pipeline")}
      pageHref={hrefFor(SCREEN)}
      page={page}
      requeueAction={page.access.allowed ? requeueEvent : null}
    />
  );
}
