import type { Tone } from "@compliancewatch/ui";
import { t, type MessageKey } from "@/shared/i18n";

/**
 * The quality numbers page (commitment 3 of guide section 1.2, trust you can see): each measure
 * from the latest evaluation run against the target it must reach (guide section 5.4), as
 * `GET /v1/eval/quality` will return them once it is designed.
 */
export interface QualityMetric {
  id: string;
  /** What is measured, for example "Citation correctness". */
  name: string;
  /** How it is measured, in a sentence. */
  description: string;
  /** The latest measurement as a share from 0 to 1; null before the first run. */
  value: number | null;
  /** The share it must reach, from 0 to 1. */
  target: number;
}

/** Where a measure stands against its target. */
export type MetricStanding = "meets" | "below" | "unmeasured";

export const METRIC_STANDINGS: readonly MetricStanding[] = ["meets", "below", "unmeasured"];

/** How many measures there are and where they stand. */
export type QualitySummary = Readonly<Record<MetricStanding | "total", number>>;

const STANDING_LABEL: Readonly<Record<MetricStanding, MessageKey>> = {
  meets: "systemQuality.standing.meets",
  below: "systemQuality.standing.below",
  unmeasured: "systemQuality.standing.unmeasured",
};

const STANDING_TONE: Readonly<Record<MetricStanding, Tone>> = {
  meets: "success",
  below: "danger",
  unmeasured: "neutral",
};

export function metricStanding(metric: Pick<QualityMetric, "value" | "target">): MetricStanding {
  if (metric.value === null) return "unmeasured";
  return metric.value >= metric.target ? "meets" : "below";
}

export function standingLabel(standing: MetricStanding): string {
  return t(STANDING_LABEL[standing]);
}

export function standingTone(standing: MetricStanding): Tone {
  return STANDING_TONE[standing];
}

/** A share as a percentage to one decimal place at most: 0.925 is "92.5%", 0.92 is "92%". */
export function formatShare(share: number): string {
  return t("systemQuality.percent", { value: Math.round(share * 1000) / 10 });
}

export function qualitySummary(metrics: readonly QualityMetric[]): QualitySummary {
  const summary = { total: metrics.length, meets: 0, below: 0, unmeasured: 0 };
  for (const metric of metrics) summary[metricStanding(metric)] += 1;
  return summary;
}
