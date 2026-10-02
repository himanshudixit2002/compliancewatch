import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { EvidenceView } from "@/features/evidence";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("owner.evidence");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function EvidencePage({
  params,
}: {
  params: { businessId: string; obligationId: string };
}) {
  const session = await requireScreenSession(SCREEN);
  return (
    <EvidenceView
      view={{
        obligationId: params.obligationId,
        obligationName: "Obligation",
        dueDate: "",
        items: [],
        canUpload: false,
        allowedTypes: ["pdf", "jpg", "png", "docx", "xlsx"],
      }}
      businessId={params.businessId}
    />
  );
}
