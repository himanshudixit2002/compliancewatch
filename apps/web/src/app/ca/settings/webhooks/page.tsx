import type { Metadata } from "next";
import { WebhooksView, emptyCaSettings } from "@/features/ca-settings";
import { requireScreenSession } from "@/server/dal";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("ca.settings.webhooks");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function WebhooksPage() {
  await requireScreenSession(SCREEN);
  const view = emptyCaSettings();

  return (
    <WebhooksView
      title={SCREEN.title}
      webhooks={view.webhooks}
    />
  );
}