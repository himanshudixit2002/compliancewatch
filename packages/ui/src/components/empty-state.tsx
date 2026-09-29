import type { ComponentProps, ReactNode } from "react";
import { InboxIcon } from "lucide-react";
import { cn } from "../lib/cn";

export interface EmptyStateProps extends Omit<ComponentProps<"div">, "title"> {
  icon?: ReactNode;
  title: ReactNode;
  /** Says why the list is empty, not just that it is. */
  body?: ReactNode;
  action?: ReactNode;
  /** Heading level; defaults to h2 because the page already has its h1. */
  heading?: "h1" | "h2" | "h3";
}

export function EmptyState({
  icon,
  title,
  body,
  action,
  heading: Heading = "h2",
  className,
  ...props
}: EmptyStateProps) {
  return (
    <div
      data-slot="empty-state"
      className={cn(
        "flex flex-col items-center gap-3 rounded-lg border border-dashed border-line-strong bg-surface p-8 text-center",
        className,
      )}
      {...props}
    >
      <span aria-hidden="true" className="text-fg-muted [&_svg]:size-8">
        {icon ?? <InboxIcon />}
      </span>
      <Heading className="text-lg font-semibold text-fg">{title}</Heading>
      {body ? <p className="max-w-prose text-sm text-fg-muted">{body}</p> : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
