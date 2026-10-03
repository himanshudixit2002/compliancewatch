import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { ObligationDetail } from "@/features/obligations";
import { hrefFor, screenById } from "@/shared/config/screens";

const SCREEN = screenById("owner.obligation");

export const metadata: Metadata = { title: "Obligation detail" };

export const dynamic = "force-dynamic";

export default async function ObligationDetailPage({
  params,
}: {
  params: { businessId: string; obligationId: string };
}) {
  const session = await requireScreenSession(SCREEN);

  return (
    <ObligationDetail
      obligation={{
        id: params.obligationId,
        businessId: params.businessId,
        title: `Obligation ${params.obligationId}`,
        description: "Loading obligation details...",
        status: "open",
        dueAt: null,
        evidenceType: "document",
        steps: [],
        ruleVersionId: "",
        decisionId: "",
        closedAt: null,
        closedReason: null,
        periodStart: null,
        periodEnd: null,
        periodLabel: null,
      }}
      evidenceHref={hrefFor(screenById("owner.evidence"), {
        businessId: params.businessId,
        obligationId: params.obligationId,
      })}
      onStatusChange={async () => {}}
    />
  );
}
