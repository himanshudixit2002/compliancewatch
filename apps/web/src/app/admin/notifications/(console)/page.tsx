import type { Metadata } from "next";
import {
  AdminNotificationsView,
  getAdminNotifications,
  readHistoryFilter,
  readLookup,
} from "@/features/notifications";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.notifications");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function AdminNotificationsPage({ searchParams }: Props) {
  const session = await requireScreenSession(SCREEN);
  const query = await searchParams;
  const lookup = readLookup(query);
  const filter = readHistoryFilter(query);
  const read =
    lookup.kind === "ok" ? await getAdminNotifications(session, lookup.lookup, filter) : null;
  return (
    <AdminNotificationsView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.notifications")}
      pageHref={hrefFor(SCREEN)}
      templatesHref={hrefFor(screenById("admin.notifications.templates"))}
      lookup={lookup}
      view={read?.ok === true ? read.value : null}
      {...(read !== null && !read.ok ? { error: read.error } : {})}
    />
  );
}
