import type { Metadata } from "next";
import {
  EntityGroupView,
  decideEntityGroup,
  getEntityGroup,
  readGroup,
} from "@/features/entity-review";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.rulebook.entities.group");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function EntityGroupPage({ searchParams }: Props) {
  const session = await requireScreenSession(SCREEN);
  const read = readGroup(await searchParams);
  const group =
    read.kind === "ok" ? await getEntityGroup(session, read.entityType, read.name) : null;
  const page = group?.ok === true ? group.value : null;
  return (
    <EntityGroupView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.rulebook.entities.group")}
      queueHref={hrefFor(screenById("admin.rulebook.entities"))}
      read={read}
      view={page?.view ?? null}
      access={page?.access ?? null}
      {...(group !== null && !group.ok ? { error: group.error } : {})}
      decide={
        read.kind === "ok" && page?.access.allowed === true
          ? decideEntityGroup.bind(null, read.entityType, read.name)
          : null
      }
    />
  );
}
