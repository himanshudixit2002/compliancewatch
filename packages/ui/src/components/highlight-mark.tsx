import type { ComponentProps } from "react";
import { cn } from "../lib/cn";
import { VisuallyHidden } from "./visually-hidden";

export interface HighlightMarkProps extends ComponentProps<"mark"> {
  /** Read by screen readers just before the marked text. */
  startLabel?: string;
  /** Read by screen readers just after it. */
  endLabel?: string;
}

/**
 * Marks a span inside running text, such as the words a mention or a quote points at. The span
 * is tinted and underlined, so it stands out without relying on colour, and screen readers hear
 * where it starts and ends (a `<mark>` alone is not announced by most of them).
 */
export function HighlightMark({
  startLabel = "Highlight starts",
  endLabel = "Highlight ends",
  className,
  children,
  ...props
}: HighlightMarkProps) {
  return (
    <>
      <VisuallyHidden>{`${startLabel}: `}</VisuallyHidden>
      <mark
        data-slot="highlight-mark"
        className={cn(
          "rounded-sm bg-warning/20 px-0.5 text-fg underline decoration-warning decoration-2 underline-offset-2",
          className,
        )}
        {...props}
      >
        {children}
      </mark>
      <VisuallyHidden>{` ${endLabel}.`}</VisuallyHidden>
    </>
  );
}
