import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { ReviewTaskDetailComponent, emptyReviewTask, type ReviewTask } from "@/features/review-task";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.review.task");

export const metadata: Metadata = { title: "Review workbench" };

export const dynamic = "force-dynamic";

interface ReviewTaskPageProps {
  params: Promise<{ taskId: string }>;
}

export default async function ReviewTaskPage({ params }: ReviewTaskPageProps) {
  await requireScreenSession(SCREEN);
  const { taskId } = await params;

  const task: ReviewTask = {
    ...emptyReviewTask(),
    id: taskId,
    title: `Review task ${taskId}`,
    description: "Placeholder task detail; the real record loads from the review-task API.",
    createdAt: new Date().toISOString(),
    dueAt: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(),
    assignee: "",
  };

  return (
    <ReviewTaskDetailComponent
      task={task}
      onApprove={() => {}}
      onReject={() => {}}
      onAssign={() => {}}
    />
  );
}