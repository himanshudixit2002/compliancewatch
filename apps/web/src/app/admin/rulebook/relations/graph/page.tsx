import type { Metadata } from "next";
import { GraphView, getGraph, readGraph } from "@/features/relations-graph";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.rulebook.relations.graph");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function RelationsGraphPage({ searchParams }: Props) {
  await requireScreenSession(SCREEN);
  const read = readGraph(await searchParams);
  const graph = read.kind === "ok" ? await getGraph(read) : null;
  const unknown =
    graph !== null &&
    !graph.ok &&
    (graph.error.kind === "not_found" || graph.error.kind === "validation");
  return (
    <GraphView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.rulebook.relations.graph")}
      pageHref={hrefFor(SCREEN)}
      read={read}
      graph={graph?.ok === true ? graph.value : null}
      unknownVersion={unknown}
      {...(graph !== null && !graph.ok && !unknown ? { error: graph.error } : {})}
    />
  );
}
