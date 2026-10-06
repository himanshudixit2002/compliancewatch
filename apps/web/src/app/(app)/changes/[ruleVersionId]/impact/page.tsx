import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  ChangeImpactView,
  getChangeImpact,
  readImpactQuery,
  sendChangeCards,
} from "@/features/change-impact";
import { IdempotencyKeyInput } from "@/server/api/idempotency";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";
import { isHexUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("ca.change-impact");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ ruleVersionId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function ChangeImpactPage({ params, searchParams }: Props) {
  const { ruleVersionId } = await params;
  const session = await requireScreenSession(SCREEN, { ruleVersionId });
  if (!isHexUuid(ruleVersionId)) notFound();
  const id = ruleVersionId.toLowerCase();
  const impact = await getChangeImpact(session, id, readImpactQuery(await searchParams));
  if (!impact.ok) {
    if (impact.error.kind === "not_found" || impact.error.kind === "validation") notFound();
    return <ServiceError heading={SCREEN.title} error={impact.error} />;
  }
  return (
    <ChangeImpactView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("ca.change-impact", { ruleVersionId: id })}
      pageHref={hrefFor(SCREEN, { ruleVersionId: id })}
      view={impact.value}
      sendAction={sendChangeCards.bind(null, id)}
      idempotencyInput={<IdempotencyKeyInput />}
    />
  );
}
