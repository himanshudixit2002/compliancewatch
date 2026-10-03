import { t } from "@/shared/i18n";

export interface DataSource {
  id: string;
  name: string;
  type: string;
  status: string;
  lastSync: string | null;
  recordCount: number;
  createdAt: string;
}

export interface AdminSourcesView {
  sources: DataSource[];
  totalCount: number;
}

export function emptyAdminSources(): AdminSourcesView {
  return { sources: [], totalCount: 0 };
}

export function dataSourceStatusTone(status: string): "success" | "info" | "danger" {
  switch (status) {
    case "connected": return "success";
    case "syncing": return "info";
    case "error": return "danger";
    default: return "neutral";
  }
}
