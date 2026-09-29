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
  /**
   * The backend is on main and only the screen is missing: the notice says so, and
   * `waitingFor` lists the routes and files the screen will use rather than ones to come.
   */
  backendReady?: boolean;
  backHref?: string;
}

function RouteList({ routes }: { routes: readonly AwaitedRoute[] }) {
  return (
    <ul className="flex flex-col gap-1 text-sm">
      {routes.map((route) => (
        <li key={`${route.method} ${route.path}`} className="flex flex-wrap items-center gap-2">
          <code className="rounded-sm bg-surface px-1.5 py-0.5 font-mono text-xs text-fg">
            {route.method} {route.path}
          </code>
          <span className="text-fg-muted">{route.owner}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * The honest page for a registered screen that is not built: its backend routes do not all
 * exist yet, or they do and the screen itself is still to be written.
 */
export function NotAvailableYet({
  title,
  guideRef,
  roles,
  waitingFor,
  backendReady = false,
  backHref = "/",
  className,
  ...props
}: NotAvailableYetProps) {
  const routes = waitingFor ?? [];
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
      {backendReady ? (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-fg">
            The backend for this screen is on main. The screen itself has not been built yet.
          </p>
          {routes.length > 0 ? (
            <>
              <p className="text-sm text-fg">It will use:</p>
              <RouteList routes={routes} />
            </>
          ) : null}
        </div>
      ) : routes.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-fg">This screen waits for:</p>
          <RouteList routes={routes} />
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
