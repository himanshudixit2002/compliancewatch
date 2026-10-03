import { t } from "@/shared/i18n";

export interface BackfillJob {
  id: string;
  name: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  startedAt: string | null;
  completedAt: string | null;
}

export interface AdminBackfillView {
  jobs: BackfillJob[];
  totalCount: number;
  runningCount: number;
}

export function emptyAdminBackfill(): AdminBackfillView {
  return { jobs: [], totalCount: 0, runningCount: 0 };
}

export function backfillStatusTone(status: BackfillJob["status"]): "info" | "warning" | "success" | "danger" {
  switch (status) {
    case "pending": return "info";
    case "running": return "warning";
    case "completed": return "success";
    case "failed": return "danger";
  }
}
