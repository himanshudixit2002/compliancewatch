import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";
import { RemindersView } from "@/features/reminders";
import { reminders } from "@/features/reminders/model/reminders";

const SCREEN = screenById("owner.reminders");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function RemindersPage() {
  const session = await requireScreenSession(SCREEN);
  const result = await reminders();
  if (!result.ok) return <ServiceError heading={SCREEN.title} error={result.error} />;
  return <RemindersView title={SCREEN.title} items={result.value} />;
}
