import type { ComponentProps } from "react";
import { cn } from "../lib/cn";

export type SkeletonProps = ComponentProps<"div">;

/** One placeholder block; hidden from assistive technology, so wrap a set in SkeletonGroup. */
export function Skeleton({ className, ...props }: SkeletonProps) {
  return (
    <div
      aria-hidden="true"
      data-slot="skeleton"
      className={cn("animate-pulse rounded-md bg-fg/10", className)}
      {...props}
    />
  );
}

export interface SkeletonGroupProps extends ComponentProps<"div"> {
  /** Announced once for the whole group. */
  label?: string;
}

export function SkeletonGroup({
  className,
  label = "Loading",
  children,
  ...props
}: SkeletonGroupProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      data-slot="skeleton-group"
      className={cn("flex flex-col gap-3", className)}
      {...props}
    >
      {children}
      <span className="sr-only">{label}</span>
    </div>
  );
}
