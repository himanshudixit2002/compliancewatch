import type { ComponentProps, ReactNode } from "react";
import { CheckIcon } from "lucide-react";
import { cn } from "../lib/cn";

export interface Step {
  id: string;
  label: ReactNode;
  description?: ReactNode;
}

export interface StepperProps extends ComponentProps<"nav"> {
  steps: readonly Step[];
  /** Zero-based index of the current step. */
  current: number;
  label?: string;
}

/** Progress through a fixed sequence, with the current step announced as such. */
export function Stepper({ steps, current, label = "Progress", className, ...props }: StepperProps) {
  return (
    <nav data-slot="stepper" aria-label={label} className={className} {...props}>
      <p className="mb-2 text-sm text-fg-muted">
        Step {Math.min(current + 1, steps.length)} of {steps.length}
      </p>
      <ol className="flex flex-col gap-2 sm:flex-row sm:gap-4">
        {steps.map((step, index) => {
          const state = index < current ? "done" : index === current ? "current" : "upcoming";
          return (
            <li
              key={step.id}
              data-state={state}
              aria-current={state === "current" ? "step" : undefined}
              className="flex flex-1 items-start gap-2"
            >
              <span
                aria-hidden="true"
                className={cn(
                  "flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold",
                  state === "done" && "border-success bg-success text-success-fg",
                  state === "current" && "border-primary bg-primary text-primary-fg",
                  state === "upcoming" && "border-line-strong text-fg-muted",
                )}
              >
                {state === "done" ? <CheckIcon className="size-3.5" /> : index + 1}
              </span>
              <span className="flex flex-col">
                <span
                  className={cn(
                    "text-sm font-medium",
                    state === "upcoming" ? "text-fg-muted" : "text-fg",
                  )}
                >
                  {step.label}
                  {state === "done" ? <span className="sr-only"> (done)</span> : null}
                </span>
                {step.description ? (
                  <span className="text-xs text-fg-muted">{step.description}</span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
