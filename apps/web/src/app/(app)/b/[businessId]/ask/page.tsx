import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AskView, askQuestion, getAskPage } from "@/features/ask";
import { businessFlags, businessHeaderLinks } from "@/features/business";
import { requireScreenSession } from "@/server/dal";
import { screenById } from "@/shared/config/screens";
import { isUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.ask");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ businessId: string }>;
}

export default async function AskPage({ params }: Props) {
  const { businessId } = await params;
  const session = await requireScreenSession(SCREEN, { businessId });
  if (!isUuid(businessId)) notFound();
  const page = await getAskPage(session, businessId);
  if (!page.ok) {
    if (page.error.kind === "not_found") notFound();
    return <ServiceError heading={SCREEN.title} error={page.error} />;
  }
  return (
    <AskView
      title={SCREEN.title}
      view={page.value}
      header={businessHeaderLinks(
        "owner.ask",
        session,
        businessId,
        page.value.business.name,
        await businessFlags(session),
      )}
      action={askQuestion}
    />
  );
}
