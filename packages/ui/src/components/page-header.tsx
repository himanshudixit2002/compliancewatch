import type { ComponentProps, ReactNode } from "react";
import { cn } from "../lib/cn";

export interface PageHeaderProps extends Omit<ComponentProps<"header">, "title"> {
  title: ReactNode;
  description?: ReactNode;
  /** A Breadcrumbs component, rendered above the title. */
  breadcrumbs?: ReactNode;
  /** Buttons or links aligned to the end of the header. */
  actions?: ReactNode;
}

/** The one h1 of a page, with its description, breadcrumbs and actions. */
export function PageHeader({
  title,
  description,
  breadcrumbs,
  actions,
  className,
  ...props
}: PageHeaderProps) {
  return (
    <header data-slot="page-header" className={cn("flex flex-col gap-3", className)} {...props}>
      {breadcrumbs}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight text-fg">{title}</h1>
          {description ? <p className="max-w-prose text-sm text-fg-muted">{description}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
      </div>
    </header>
  );
}
