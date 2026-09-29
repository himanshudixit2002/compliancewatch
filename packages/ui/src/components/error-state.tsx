import type { ComponentProps, ReactNode } from "react";
import { CircleAlertIcon } from "lucide-react";
import { cn } from "../lib/cn";
import { Button } from "./button";
import { CopyButton } from "./copy-button";

export interface ErrorStateProps extends Omit<ComponentProps<"div">, "title"> {
  title: ReactNode;
  /** The problem detail from the service, if any. */
  detail?: ReactNode;
  /** The x-request-id sent with the failed call; support finds the log line with it. */
  correlationId?: string;
  status?: number;
  retryHref?: string;
  /** Extra controls, such as a client-side retry button. */
  action?: ReactNode;
}

/** What went wrong, the service's own words, and the id to quote to support. */
export function ErrorState({
  title,
  detail,
  correlationId,
  status,
  retryHref,
  action,
  className,
  ...props
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      data-slot="error-state"
      data-status={status}
      className={cn(
        "flex flex-col gap-3 rounded-lg border border-danger bg-danger/10 p-6 text-fg",
        className,
      )}
      {...props}
    >
      <div className="flex items-start gap-3">
        <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-danger" />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="font-semibold">
            {title}
            {status !== undefined ? (
              <span className="ml-2 text-sm font-normal text-fg-muted">HTTP {status}</span>
            ) : null}
          </p>
          {detail ? <p className="text-sm text-fg-muted">{detail}</p> : null}
        </div>
      </div>
      {correlationId ? (
        <p className="flex flex-wrap items-center gap-2 text-sm text-fg-muted">
          <span>Correlation id</span>
          <code
            data-slot="correlation-id"
            className="rounded-sm bg-surface px-1.5 py-0.5 font-mono text-fg"
          >
            {correlationId}
          </code>
          <CopyButton value={correlationId} label="Copy correlation id" size="sm" />
        </p>
      ) : null}
      {retryHref || action ? (
        <div className="flex flex-wrap gap-2">
          {retryHref ? (
            <Button asChild variant="secondary">
              <a href={retryHref}>Try again</a>
            </Button>
          ) : null}
          {action}
        </div>
      ) : null}
    </div>
  );
}
