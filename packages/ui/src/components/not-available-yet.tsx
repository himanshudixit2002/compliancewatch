import type { ComponentProps, ReactNode } from "react";
import { cn } from "../lib/cn";
import { Button } from "./button";

export interface AwaitedRoute {
  method: string;
  path: string;
  /** Who is building it, as the app labels the owner. */
  owner: string;
}

export interface NotAvailableYetProps extends Omit<ComponentProps<"section">, "title"> {
  title: ReactNode;
  guideRef: string;
  roles: readonly string[];
  /** The routes the screen waits for, or null when no backend exists or is scheduled. */
  waitingFor: readonly AwaitedRoute[] | null;
  backHref?: string;
}

/** The honest page for a registered screen whose backend routes do not exist yet. */
export function NotAvailableYet({
  title,
  guideRef,
  roles,
  waitingFor,
  backHref = "/",
  className,
  ...props
}: NotAvailableYetProps) {
  return (
    <section
      data-slot="not-available-yet"
      className={cn(
        "flex max-w-2xl flex-col gap-4 rounded-lg border bg-surface-raised p-6",
        className,
      )}
      {...props}
    >
      <div className="flex flex-col gap-1">
        <p className="text-sm font-medium text-warning">Not available yet</p>
        <h1 className="text-2xl font-semibold text-fg">{title}</h1>
      </div>
      <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
        <dt className="text-fg-muted">Guide reference</dt>
        <dd className="text-fg">{guideRef}</dd>
        <dt className="text-fg-muted">Roles</dt>
        <dd className="text-fg">{roles.join(", ")}</dd>
      </dl>
      {waitingFor && waitingFor.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-fg">This screen waits for:</p>
          <ul className="flex flex-col gap-1 text-sm">
            {waitingFor.map((route) => (
              <li
                key={`${route.method} ${route.path}`}
                className="flex flex-wrap items-center gap-2"
              >
                <code className="rounded-sm bg-surface px-1.5 py-0.5 font-mono text-xs text-fg">
                  {route.method} {route.path}
                </code>
                <span className="text-fg-muted">{route.owner}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-sm text-fg">No backend exists for this tool yet.</p>
      )}
      <div>
        <Button asChild variant="secondary">
          <a href={backHref}>Back</a>
        </Button>
      </div>
    </section>
  );
}
