import type { ComponentProps } from "react";
import { cn } from "../lib/cn";

export interface TableProps extends ComponentProps<"table"> {
  /**
   * Names the scroll container and makes it a focusable region, for a table that can be wider
   * than its column: a keyboard user tabs to it and scrolls it with the arrow keys.
   */
  scrollLabel?: string;
}

/** Semantic table primitives; give every table a TableCaption and scope on TableHead. */
export function Table({ className, scrollLabel, ...props }: TableProps) {
  const region =
    scrollLabel === undefined
      ? {}
      : { role: "region", "aria-label": scrollLabel, tabIndex: 0 as const };
  return (
    <div
      data-slot="table-container"
      className="relative w-full overflow-x-auto rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-focus/50"
      {...region}
    >
      <table
        data-slot="table"
        className={cn("w-full caption-bottom text-sm", className)}
        {...props}
      />
    </div>
  );
}

export function TableHeader({ className, ...props }: ComponentProps<"thead">) {
  return <thead data-slot="table-header" className={cn("[&_tr]:border-b", className)} {...props} />;
}

export function TableBody({ className, ...props }: ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  );
}

export function TableFooter({ className, ...props }: ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn("border-t bg-surface font-medium [&>tr]:last:border-b-0", className)}
      {...props}
    />
  );
}

export function TableRow({ className, ...props }: ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "border-b transition-colors hover:bg-fg/5 data-[state=selected]:bg-surface",
        className,
      )}
      {...props}
    />
  );
}

export function TableHead({ className, scope = "col", ...props }: ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      scope={scope}
      className={cn(
        "h-10 px-2 text-left align-middle font-medium whitespace-nowrap text-fg [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
        className,
      )}
      {...props}
    />
  );
}

export function TableCell({ className, ...props }: ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "p-2 align-middle whitespace-nowrap [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
        className,
      )}
      {...props}
    />
  );
}

export function TableCaption({ className, ...props }: ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("mt-4 text-sm text-fg-muted", className)}
      {...props}
    />
  );
}
