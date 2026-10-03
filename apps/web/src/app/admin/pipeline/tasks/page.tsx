import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { PipelineViewComponent } from "@/features/admin-pipeline";
import { emptyPipeline } from "@/features/admin-pipeline/model/pipeline";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.pipeline.tasks");

export const metadata: Metadata = { title: "Pipeline tasks" };

export const dynamic = "force-dynamic";

export default async function AdminPipelineTasksPage() {
  await requireScreenSession(SCREEN);

  return <PipelineViewComponent view={emptyPipeline()} />;
}