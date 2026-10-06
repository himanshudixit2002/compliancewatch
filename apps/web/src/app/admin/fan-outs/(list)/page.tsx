import type { Metadata } from "next";
import { FanOutsView, getFanOutList, readCursor, setFanOutHold } from "@/features/fan-outs";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.fan-outs");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function FanOutsPage({ searchParams }: Props) {
  const session = await requireScreenSession(SCREEN);
  const list = await getFanOutList(session, readCursor((await searchParams).cursor));
  if (!list.ok) return <ServiceError heading={SCREEN.title} error={list.error} />;
  return (
    <FanOutsView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.fan-outs")}
      view={list.value}
      holdAction={setFanOutHold.bind(null, null)}
    />
  );
}
