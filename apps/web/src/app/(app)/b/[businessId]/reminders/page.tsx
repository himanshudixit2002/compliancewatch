import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { businessFlags, businessHeaderLinks } from "@/features/business";
import { RemindersView, getReminders, readHistoryFilter } from "@/features/notifications";
import { requireScreenSession } from "@/server/dal";
import { hrefFor, screenById } from "@/shared/config/screens";
import { isUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.reminders");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ businessId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function RemindersPage({ params, searchParams }: Props) {
  const { businessId } = await params;
  const session = await requireScreenSession(SCREEN, { businessId });
  if (!isUuid(businessId)) notFound();
  const page = await getReminders(session, businessId, readHistoryFilter(await searchParams));
  if (!page.ok) {
    if (page.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={page.error} />;
  }
  return (
    <RemindersView
      title={SCREEN.title}
      view={page.value}
      header={businessHeaderLinks(
        "owner.reminders",
        session,
        businessId,
        page.value.business.name,
        await businessFlags(session),
      )}
      pageHref={hrefFor(SCREEN, { businessId })}
    />
  );
}
