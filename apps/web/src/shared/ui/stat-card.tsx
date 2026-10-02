import type { ReactNode } from "react";
import { Card, cn } from "@compliancewatch/ui";
import type { Tone } from "@compliancewatch/ui";

export interface StatCardProps {
  label: string;
  value: string | number;
  /** Reinforces the label with a coloured edge; the label still says what the number is. */
  tone?: Tone;
  /** Optional line under the value, such as what the count covers. */
  hint?: ReactNode;
  className?: string;
}

const TONE_EDGE: Readonly<Record<Tone, string>> = {
  neutral: "border-l-line",
  success: "border-l-success",
  warning: "border-l-warning",
  danger: "border-l-danger",
  info: "border-l-info",
};

/** One labelled figure for a summary row: the label first, then the value, then a hint. */
export function StatCard({ label, value, tone = "neutral", hint, className }: StatCardProps) {
  return (
    <Card
      data-slot="stat-card"
      data-tone={tone}
      className={cn("gap-1 border-l-4 px-4 py-3", TONE_EDGE[tone], className)}
    >
      <dl className="flex flex-col gap-1">
        <dt className="text-sm text-fg-muted">{label}</dt>
        <dd className="text-2xl font-semibold text-fg">{value}</dd>
      </dl>
      {hint ? <p className="text-xs text-fg-muted">{hint}</p> : null}
    </Card>
  );
}
