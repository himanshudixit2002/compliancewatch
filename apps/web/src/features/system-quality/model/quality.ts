import { t } from "@/shared/i18n";

export interface QualityMetric {
  id: string;
  name: string;
  value: number;
  target: number;
  unit: string;
  status: "healthy" | "warning" | "critical";
}

export interface SystemQualityView {
  metrics: QualityMetric[];
  overallScore: number;
}

export function emptySystemQuality(): SystemQualityView {
  return { metrics: [], overallScore: 0 };
}
