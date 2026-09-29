import type { ComponentProps } from "react";
import { cn } from "../lib/cn";
import type { Tone } from "../tokens";

const dotClasses: Record<Tone, string> = {
  neutral: "bg-fg-muted",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
};

/** snake_case or kebab-case status values read as a sentence: "not_started" to "Not started". */
export function humaniseStatus(status: string): string {
  const words = status.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export interface StatusChipProps extends Omit<ComponentProps<"span">, "children"> {
  /** The domain value, for example "due_soon"; shown humanised unless a label is given. */
  status: string;
  tone?: Tone;
  label?: string;
}

/** A coloured dot next to a text label; the text carries the meaning, never the colour alone. */
export function StatusChip({
  status,
  tone = "neutral",
  label,
  className,
  ...props
}: StatusChipProps) {
  const text = label ?? humaniseStatus(status);
  return (
    <span
      data-slot="status-chip"
      data-status={status}
      data-tone={tone}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-2 py-0.5 text-xs font-medium text-fg",
        className,
      )}
      {...props}
    >
      <span aria-hidden="true" className={cn("size-2 shrink-0 rounded-full", dotClasses[tone])} />
      {text}
    </span>
  );
}
