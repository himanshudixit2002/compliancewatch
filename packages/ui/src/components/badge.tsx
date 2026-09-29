import type { ComponentProps } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import { cn } from "../lib/cn";
import type { Tone } from "../tokens";

export const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-full border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap focus-visible:ring-2 focus-visible:ring-focus focus-visible:outline-none [&>svg]:pointer-events-none [&>svg]:size-3",
  {
    variants: {
      tone: {
        neutral: "border-line bg-surface text-fg",
        success: "bg-success text-success-fg",
        warning: "bg-warning text-warning-fg",
        danger: "bg-danger text-danger-fg",
        info: "bg-info text-info-fg",
      } satisfies Record<Tone, string>,
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type BadgeTone = Tone;

export interface BadgeProps extends ComponentProps<"span">, VariantProps<typeof badgeVariants> {
  asChild?: boolean;
}

/** Small status label. The text carries the meaning; the tone only reinforces it. */
export function Badge({ className, tone = "neutral", asChild = false, ...props }: BadgeProps) {
  const Comp = asChild ? Slot.Root : "span";
  return (
    <Comp
      data-slot="badge"
      data-tone={tone}
      className={cn(badgeVariants({ tone }), className)}
      {...props}
    />
  );
}
