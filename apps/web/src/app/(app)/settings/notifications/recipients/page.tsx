import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  RecipientsView,
  getRecipientsPage,
  removeRecipient,
  saveRecipient,
} from "@/features/notification-recipients";
import { requireScreenSession } from "@/server/dal";
import { settingsHeaderLinks } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";
import { isUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.settings.notification-recipients");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

/** A query value that is a UUID, lower-cased; anything else counts as absent. */
function uuidOf(value: string | string[] | undefined): string | undefined {
  const first = Array.isArray(value) ? value[0] : value;
  return first !== undefined && isUuid(first) ? first.toLowerCase() : undefined;
}

export default async function NotificationRecipientsPage({ searchParams }: Props) {
  const session = await requireScreenSession(SCREEN);
  const query = await searchParams;
  const businessId = uuidOf(query.business);
  const editId = uuidOf(query.edit);
  const saved = uuidOf(query.saved);
  const pageHref = hrefFor(SCREEN);
  const page = await getRecipientsPage(
    session,
    {
      ...(businessId === undefined ? {} : { businessId }),
      ...(editId === undefined ? {} : { editId }),
    },
    pageHref,
  );
  if (!page.ok) {
    if (page.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={page.error} />;
  }
  const { crumbs, tabs } = settingsHeaderLinks(SCREEN, session);
  return (
    <RecipientsView
      title={SCREEN.title}
      crumbs={crumbs}
      tabs={tabs}
      view={page.value}
      pageHref={pageHref}
      status={{
        ...(saved === undefined ? {} : { saved }),
        ...(query.removed === "1" ? { removed: true } : {}),
      }}
      saveAction={saveRecipient}
      removeAction={removeRecipient}
      addBusinessHref={hrefFor(screenById("owner.onboarding.business"))}
    />
  );
}
