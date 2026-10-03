import { t } from "@/shared/i18n";

export interface QaItem {
  id: string;
  title: string;
  category: string;
  priority: string;
  status: string;
  assignee: string;
  createdAt: string;
}

export interface AdminQaTriageView {
  items: QaItem[];
  totalCount: number;
}

export function emptyAdminQaTriage(): AdminQaTriageView {
  return { items: [], totalCount: 0 };
}

export function qaPriorityTone(priority: string): "success" | "warning" | "danger" | "info" {
  switch (priority) {
    case "low": return "info";
    case "medium": return "warning";
    case "high": return "danger";
    default: return "neutral";
  }
}
