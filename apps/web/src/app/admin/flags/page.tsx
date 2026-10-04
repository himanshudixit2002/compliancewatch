import type { Metadata } from "next";
import { FlagsView, getFlagConsole } from "@/features/flags";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.flags");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function FlagsPage() {
  const session = await requireScreenSession(SCREEN);
  const view = await getFlagConsole(session);
  return <FlagsView title={SCREEN.title} crumbs={breadcrumbsFor("admin.flags")} view={view} />;
}
