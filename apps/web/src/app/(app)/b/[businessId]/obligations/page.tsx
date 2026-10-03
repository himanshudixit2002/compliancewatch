import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { ObligationsViewComponent } from "@/features/obligations";
import { emptyObligations } from "@/features/obligations";
import { hrefFor, screenById } from "@/shared/config/screens";

const SCREEN = screenById("owner.obligations");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function ObligationsPage({ params }: { params: { businessId: string } }) {
  const session = await requireScreenSession(SCREEN);

  return (
    <ObligationsViewComponent
      view={emptyObligations(params.businessId)}
      businessId={params.businessId}
      href={(id) =>
        hrefFor(screenById("owner.obligation"), { businessId: params.businessId, obligationId: id })
      }
    />
  );
}
