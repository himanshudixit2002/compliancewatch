import { ErrorState, PageHeader } from "@compliancewatch/ui";

/**
 * What a page shows when its read failed: the problem's title (or the default sentence for the
 * kind of failure), the service's detail, the HTTP status and the correlation id, which is the
 * x-request-id the server layer sent and the log line support searches for. The error is taken
 * structurally, so this isomorphic module needs nothing from the server layer; server/result.ts's
 * ApiError fits it. With `heading` it is a whole page: the screen's h1, then the error.
 */
export interface ServiceErrorLike {
  message: string;
  status?: number;
  requestId: string;
  problem?: { detail?: string | null };
}

export interface ServiceErrorProps {
  error: ServiceErrorLike;
  /** The page's title, rendered as its one h1 above the error. */
  heading?: string;
  className?: string;
}

export function ServiceError({ error, heading, className }: ServiceErrorProps) {
  const state = (
    <ErrorState
      title={error.message}
      detail={error.problem?.detail ?? undefined}
      status={error.status}
      correlationId={error.requestId === "" ? undefined : error.requestId}
      className={heading === undefined ? className : undefined}
    />
  );
  if (heading === undefined) return state;
  return (
    <div data-slot="service-error-page" className={className ?? "flex max-w-3xl flex-col gap-6"}>
      <PageHeader title={heading} />
      {state}
    </div>
  );
}
