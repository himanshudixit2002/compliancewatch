import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  SourceView,
  editSource,
  fetchSource,
  getSourcePage,
  readCursor,
} from "@/features/admin-sources";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.source");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

const SOURCE_KEY = /^[a-z][a-z0-9_]{0,62}$/;

interface Props {
  params: Promise<{ key: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function SourcePage({ params, searchParams }: Props) {
  const { key } = await params;
  const session = await requireScreenSession(SCREEN, { key });
  if (!SOURCE_KEY.test(key)) notFound();
  const cursor = readCursor((await searchParams).cursor);
  const page = await getSourcePage(session, key, cursor);
  if (!page.ok) return <ServiceError heading={SCREEN.title} error={page.error} />;
  if (page.value === null) notFound();
  const name = page.value.facts.name;
  const crumbs = breadcrumbsFor("admin.source", { key }).map((crumb) =>
    crumb.id === SCREEN.id ? { ...crumb, label: name } : crumb,
  );
  const allowed = page.value.access.allowed;
  return (
    <SourceView
      title={name}
      crumbs={crumbs}
      page={page.value}
      editAction={allowed ? editSource.bind(null, key) : null}
      fetchAction={allowed ? fetchSource.bind(null, key) : null}
    />
  );
}
