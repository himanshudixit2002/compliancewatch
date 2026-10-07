import type { Metadata } from "next";
import { notFound } from "next/navigation";
import {
  WorkbenchView,
  claimTask,
  decideTask,
  draftFromCandidate,
  editDraft,
  getWorkbench,
} from "@/features/review-tasks";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { isHexUuid } from "@/shared/lib/identifiers";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.review.task");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  params: Promise<{ taskId: string }>;
}

export default async function ReviewWorkbenchPage({ params }: Props) {
  const { taskId } = await params;
  const session = await requireScreenSession(SCREEN, { taskId });
  if (!isHexUuid(taskId)) notFound();
  const id = taskId.toLowerCase();
  const page = await getWorkbench(session, id);
  if (!page.ok) return <ServiceError heading={SCREEN.title} error={page.error} />;
  if (page.value === null) notFound();
  const view = page.value;
  const needingTarget = (view.rule.draftForm?.relations ?? [])
    .filter((relation) => relation.needsTarget)
    .map((relation) => relation.candidateId);
  return (
    <WorkbenchView
      crumbs={breadcrumbsFor("admin.review.task", { taskId: id })}
      view={view}
      actions={
        view.access.allowed
          ? {
              claim: claimTask.bind(null, id),
              draft: draftFromCandidate.bind(null, id, needingTarget),
              edit: editDraft.bind(null, id),
              decide: decideTask.bind(null, id, view.candidateTask),
            }
          : null
      }
    />
  );
}
