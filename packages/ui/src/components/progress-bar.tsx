import type { ComponentProps, ReactNode } from "react";
import { useId } from "react";
import { cn } from "../lib/cn";

export interface ProgressBarProps extends Omit<ComponentProps<"div">, "children"> {
  /** What is progressing, shown above the bar and naming it ("Onboarding progress"). */
  label: ReactNode;
  value: number;
  /** Defaults to 100. */
  max?: number;
  /** The progress in words, shown next to the label and read out instead of a percentage. */
  valueText?: string;
}

/**
 * How far along something is, as `role="progressbar"` with its value, range and value text, so
 * a screen reader says "4 of 17 answered" rather than a percentage. The value is clamped to the
 * range; the track has a 3:1 border so the bar's extent reads without colour.
 */
export function ProgressBar({
  label,
  value,
  max = 100,
  valueText,
  className,
  ...props
}: ProgressBarProps) {
  const labelId = useId();
  const top = max > 0 ? max : 0;
  const current = Math.min(Math.max(value, 0), top);
  const percent = top === 0 ? 100 : Math.round((current / top) * 100);
  return (
    <div data-slot="progress-bar" className={cn("grid gap-1.5", className)} {...props}>
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span id={labelId} className="font-medium text-fg">
          {label}
        </span>
        {valueText ? <span className="text-fg-muted">{valueText}</span> : null}
      </div>
      <div
        role="progressbar"
        aria-labelledby={labelId}
        aria-valuemin={0}
        aria-valuemax={top}
        aria-valuenow={current}
        aria-valuetext={valueText}
        className="h-2.5 w-full overflow-hidden rounded-full border border-line-strong bg-surface"
      >
        <div
          data-slot="progress-bar-fill"
          className="h-full rounded-full bg-primary transition-[width]"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}
