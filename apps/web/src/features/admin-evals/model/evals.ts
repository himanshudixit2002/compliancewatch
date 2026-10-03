import { t } from "@/shared/i18n";

export interface EvalRun {
  id: string;
  name: string;
  model: string;
  status: string;
  createdAt: string;
  score: number | null;
}

export interface AdminEvalsView {
  runs: EvalRun[];
  totalCount: number;
}

export function emptyAdminEvals(): AdminEvalsView {
  return { runs: [], totalCount: 0 };
}

export function evalScoreTone(score: number | null): "success" | "warning" | "danger" {
  if (score === null) return "neutral";
  if (score >= 0.8) return "success";
  if (score >= 0.5) return "warning";
  return "danger";
}
