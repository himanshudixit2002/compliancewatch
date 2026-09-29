import type { ComponentProps } from "react";
import { cn } from "../lib/cn";

export type TextareaProps = ComponentProps<"textarea">;

export function Textarea({ className, ...props }: TextareaProps) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex field-sizing-content min-h-16 w-full rounded-md border border-line-strong bg-surface-raised px-3 py-2 text-base text-fg shadow-xs transition-[color,box-shadow] outline-none placeholder:text-fg-muted focus-visible:border-focus focus-visible:ring-2 focus-visible:ring-focus/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-danger aria-invalid:ring-danger/30 md:text-sm",
        className,
      )}
      {...props}
    />
  );
}
