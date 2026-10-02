import type { Metadata } from "next";
import { FlagsView, flags, defaultFlags } from "@/features/flags";
import { requireAdmin } from "@/server/dal";
import { hrefFor, screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.flags");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function AdminFlagsPage() {
  await requireAdmin({ next: hrefFor(SCREEN) });
  const result = await flags();
  if (!result.ok) {
    return <ServiceError heading={SCREEN.title} error={result.error} />;
  }
  return <FlagsView title={SCREEN.title} items={result.value} />;
}
