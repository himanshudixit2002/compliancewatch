import type { Metadata } from "next";
import { UsageView, getUsage, readUsage } from "@/features/llm-registry";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.llm.usage");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function UsagePage({ searchParams }: Props) {
  await requireScreenSession(SCREEN);
  const read = readUsage(await searchParams);
  const usage = read.kind === "invalid" ? null : await getUsage(read);
  return (
    <UsageView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.llm.usage")}
      pageHref={hrefFor(SCREEN)}
      read={read}
      view={usage?.ok === true ? usage.value : null}
      {...(usage !== null && !usage.ok ? { error: usage.error } : {})}
    />
  );
}
