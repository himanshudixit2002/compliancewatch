import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@compliancewatch/ui";
import { cn } from "@compliancewatch/ui";

export interface StatCardProps {
  label: string;
  value: string | number;
  icon?: ReactNode;
  tone?: "default" | "success" | "warning" | "danger" | "info";
  href?: string;
  loading?: boolean;
}

const TONE_CLASSES: Record<NonNullable<StatCardProps["tone"]>, string> = {
  default: "border-line bg-surface",
  success: "border-emerald-200 bg-emerald-50/50 dark:border-emerald-800 dark:bg-emerald-950/30",
  warning: "border-amber-200 bg-amber-50/50 dark:border-amber-800 dark:bg-amber-950/30",
  danger: "border-red-200 bg-red-50/50 dark:border-red-800 dark:bg-red-950/30",
  info: "border-sky-200 bg-sky-50/50 dark:border-sky-800 dark:bg-sky-950/30",
};

const TONE_ICON: Record<NonNullable<StatCardProps["tone"]>, string> = {
  default: "text-fg-muted",
  success: "text-emerald-600 dark:text-emerald-400",
  warning: "text-amber-600 dark:text-amber-400",
  danger: "text-red-600 dark:text-red-400",
  info: "text-sky-600 dark:text-sky-400",
};

export function StatCard({
  label,
  value,
  icon,
  tone = "default",
  href,
  loading = false,
}: StatCardProps) {
  const inner = (
    <Card className={cn("gap-3 transition-shadow hover:shadow-md", TONE_CLASSES[tone])}>
      <CardHeader className="flex flex-row items-center justify-between px-4 pb-2 pt-4">
        <CardTitle className="text-sm font-medium text-fg-muted">{label}</CardTitle>
        {icon ? <span className={cn("h-5 w-5", TONE_ICON[tone])}>{icon}</span> : null}
      </CardHeader>
      <CardContent className="px-4 pb-4">
        {loading ? (
          <div className="h-8 w-24 animate-pulse rounded bg-line" />
        ) : (
          <p className="text-2xl font-semibold tracking-tight text-fg">{value}</p>
        )}
      </CardContent>
    </Card>
  );

  if (href) {
    return (
      <a href={href} className="block no-underline">
        {inner}
      </a>
    );
  }
  return inner;
}
