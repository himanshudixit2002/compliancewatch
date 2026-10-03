import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { EvidenceViewComponent } from "@/features/evidence";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("owner.evidence");

export const metadata: Metadata = { title: "Evidence" };

export const dynamic = "force-dynamic";

export default async function EvidencePage({
  params,
}: {
  params: { businessId: string; obligationId: string };
}) {
  const session = await requireScreenSession(SCREEN);

  return (
    <EvidenceViewComponent
      view={{
        obligationName: `Obligation ${params.obligationId}`,
        dueDate: null,
        items: [],
      }}
      onUpload={async () => {}}
      onDelete={async () => {}}
      onPreview={() => {}}
    />
  );
}
