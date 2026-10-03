import type { Metadata } from "next";
import { DigestsView, emptyCaSettings } from "@/features/ca-settings";
import { requireScreenSession } from "@/server/dal";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("ca.settings.digests");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function DigestsPage() {
  await requireScreenSession(SCREEN);
  const view = emptyCaSettings();

  return (
    <DigestsView
      title={SCREEN.title}
      config={view.digests[0] ?? null}
    />
  );
}