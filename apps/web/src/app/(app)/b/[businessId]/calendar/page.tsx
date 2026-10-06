import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { businessFlags, businessHeaderLinks } from "@/features/business";
import { CalendarView, getCalendar, loadCalendarMonth, readMonth } from "@/features/obligations";
import { requireScreenSession } from "@/server/dal";
import { hrefFor, screenById } from "@/shared/config/screens";
import { isUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.calendar");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ businessId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function CalendarPage({ params, searchParams }: Props) {
  const { businessId } = await params;
  const session = await requireScreenSession(SCREEN, { businessId });
  if (!isUuid(businessId)) notFound();
  const month = readMonth((await searchParams).month);
  const calendar = await getCalendar(session, businessId, month);
  if (!calendar.ok) {
    if (calendar.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={calendar.error} />;
  }
  return (
    <CalendarView
      title={SCREEN.title}
      view={calendar.value}
      header={businessHeaderLinks(
        "owner.calendar",
        session,
        businessId,
        calendar.value.business.name,
        await businessFlags(session),
      )}
      load={loadCalendarMonth.bind(null, businessId)}
      pageHref={hrefFor(SCREEN, { businessId })}
      listHref={hrefFor(screenById("owner.obligations"), { businessId })}
    />
  );
}
