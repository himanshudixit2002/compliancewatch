import { t } from "@/shared/i18n";

export interface PipelineTask {
  id: string;
  name: string;
  type: string;
  status: "pending" | "running" | "completed" | "failed";
  startedAt: string | null;
  completedAt: string | null;
  duration: string | null;
  progress: number;
  error: string | null;
}

export interface PipelineView {
  tasks: PipelineTask[];
  totalCount: number;
  runningCount: number;
  failedCount: number;
  completedCount: number;
}

export function emptyPipeline(): PipelineView {
  return {
    tasks: [],
    totalCount: 0,
    runningCount: 0,
    failedCount: 0,
    completedCount: 0,
  };
}

export function pipelineStatusTone(status: PipelineTask["status"]): "info" | "success" | "warning" | "danger" {
  switch (status) {
    case "pending": return "info";
    case "running": return "warning";
    case "completed": return "success";
    case "failed": return "danger";
  }
}
