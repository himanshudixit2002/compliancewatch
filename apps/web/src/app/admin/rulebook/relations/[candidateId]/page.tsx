import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  CandidateView,
  approveCandidate,
  getCandidatePage,
  rejectCandidate,
} from "@/features/relation-review";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { isHexUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.rulebook.relation");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ candidateId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function RelationCandidatePage({ params, searchParams }: Props) {
  const { candidateId } = await params;
  const session = await requireScreenSession(SCREEN, { candidateId });
  if (!isHexUuid(candidateId)) notFound();
  const status = (await searchParams).status;
  const page = await getCandidatePage(
    session,
    candidateId.toLowerCase(),
    typeof status === "string" ? status : undefined,
  );
  if (!page.ok) return <ServiceError heading={SCREEN.title} error={page.error} />;
  if (page.value === null) notFound();
  const id = page.value.facts.candidateId;
  const allowed = page.value.access.allowed;
  return (
    <CandidateView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.rulebook.relation", { candidateId: id })}
      page={page.value}
      approve={allowed ? approveCandidate.bind(null, id) : null}
      reject={allowed ? rejectCandidate.bind(null, id) : null}
    />
  );
}
