import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { SystemQualityViewComponent } from "@/features/system-quality";
import { emptySystemQuality } from "@/features/system-quality/model/quality";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("system.quality");

export const metadata: Metadata = { title: "System quality" };

export const dynamic = "force-dynamic";

export default async function SystemQualityPage() {
  await requireScreenSession(SCREEN);

  return <SystemQualityViewComponent view={emptySystemQuality()} />;
}