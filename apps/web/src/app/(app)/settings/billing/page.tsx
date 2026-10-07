import type { Metadata } from "next";
import {
  BillingView,
  SUBSCRIBE_FIELDS,
  getBillingPage,
  startSubscription,
} from "@/features/billing";
import { IdempotencyKeyInput } from "@/server/api/idempotency";
import { requireScreenSession } from "@/server/dal";
import { settingsHeaderLinks } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.settings.billing");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function BillingPage() {
  const session = await requireScreenSession(SCREEN);
  const page = await getBillingPage(session);
  if (!page.ok) return <ServiceError heading={SCREEN.title} error={page.error} />;
  const { crumbs, tabs } = settingsHeaderLinks(SCREEN, session);
  return (
    <BillingView
      title={SCREEN.title}
      plans={page.value.plans}
      crumbs={crumbs}
      tabs={tabs}
      action={startSubscription}
      fields={SUBSCRIBE_FIELDS}
      idempotencyInput={<IdempotencyKeyInput />}
    />
  );
}
