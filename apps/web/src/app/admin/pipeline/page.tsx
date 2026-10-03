import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { PipelineViewComponent } from "@/features/admin-pipeline";
import { emptyPipeline } from "@/features/admin-pipeline/model/pipeline";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.pipeline");

export const metadata: Metadata = { title: "Pipeline" };

export const dynamic = "force-dynamic";

export default async function AdminPipelinePage() {
  await requireScreenSession(SCREEN);

  return <PipelineViewComponent view={emptyPipeline()} />;
}
