import type { ComponentProps } from "react";
import { cn } from "../lib/cn";

export type VisuallyHiddenProps = ComponentProps<"span">;

/** Text for assistive technology only. */
export function VisuallyHidden({ className, ...props }: VisuallyHiddenProps) {
  return <span data-slot="visually-hidden" className={cn("sr-only", className)} {...props} />;
}
