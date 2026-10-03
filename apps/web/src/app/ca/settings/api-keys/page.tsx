import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { ApiKeysView } from "@/features/ca-settings";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("ca.settings.api-keys");

export const metadata: Metadata = { title: "API keys" };

export const dynamic = "force-dynamic";

export default async function CaApiKeysPage() {
  await requireScreenSession(SCREEN);

  return <ApiKeysView />;
}