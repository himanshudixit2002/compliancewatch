import type { Metadata } from "next";
import { ResolveView, getResolution, readResolve } from "@/features/rulebook-entities";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.rulebook.canonical");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function CanonicalEntitiesPage({ searchParams }: Props) {
  await requireScreenSession(SCREEN);
  const read = readResolve(await searchParams);
  const resolution = read.kind === "ok" ? await getResolution(read.entityType, read.name) : null;
  return (
    <ResolveView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.rulebook.canonical")}
      pageHref={hrefFor(SCREEN)}
      read={read}
      resolution={resolution?.ok === true ? resolution.value : null}
      {...(resolution !== null && !resolution.ok ? { error: resolution.error } : {})}
    />
  );
}
