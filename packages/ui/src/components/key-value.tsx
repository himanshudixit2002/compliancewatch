import type { ComponentProps, ReactNode } from "react";
import { cn } from "../lib/cn";
import { CopyButton } from "./copy-button";

export interface KeyValueItem {
  key: string;
  label: ReactNode;
  value: ReactNode;
  /** When set, a copy button writes this text to the clipboard. */
  copy?: string;
  /** Accessible name of that button; defaults to "Copy <label>" for a string label. */
  copyLabel?: string;
}

export interface KeyValueProps extends ComponentProps<"dl"> {
  items: readonly KeyValueItem[];
  /** Two columns on wide screens, or one label-over-value column. */
  layout?: "grid" | "stack";
}

/** A description list of label and value pairs, for headers and detail panels. */
export function KeyValue({ items, layout = "grid", className, ...props }: KeyValueProps) {
  return (
    <dl
      data-slot="key-value"
      className={cn(
        "grid gap-x-6 gap-y-2 text-sm",
        layout === "grid" ? "sm:grid-cols-[max-content_1fr]" : "grid-cols-1",
        className,
      )}
      {...props}
    >
      {items.map((item) => (
        <div key={item.key} className="contents">
          <dt className="font-medium text-fg-muted">{item.label}</dt>
          <dd className="flex items-center gap-1 text-fg">
            {item.value}
            {item.copy ? (
              <CopyButton
                value={item.copy}
                label={
                  item.copyLabel ?? (typeof item.label === "string" ? `Copy ${item.label}` : "Copy")
                }
                size="sm"
              />
            ) : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}
