import type { Metadata } from "next";
import {
  TasksView,
  dismissTask,
  getTasksPage,
  readTaskQuery,
  resolveTask,
} from "@/features/admin-pipeline";
import { requireScreenSession } from "@/server/dal";
import { breadcrumbsFor } from "@/shared/config/nav";
import { screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.pipeline.tasks");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function PipelineTasksPage({ searchParams }: Props) {
  const session = await requireScreenSession(SCREEN);
  const filter = readTaskQuery(await searchParams);
  const page = await getTasksPage(session, filter);
  if (!page.ok) return <ServiceError heading={SCREEN.title} error={page.error} />;
  return (
    <TasksView
      title={SCREEN.title}
      crumbs={breadcrumbsFor("admin.pipeline.tasks")}
      view={page.value.view}
      access={page.value.access}
      actionsFor={
        page.value.access.allowed
          ? (card) => ({
              resolve: resolveTask.bind(null, card.taskId, card.kind),
              dismiss: dismissTask.bind(null, card.taskId),
            })
          : null
      }
    />
  );
}
