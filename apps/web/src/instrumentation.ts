import type { Instrumentation } from "next";

/**
 * Server errors as one JSON line on stderr, keyed so a log search finds them: the digest the
 * error page shows, the route, and the request id we received. Nothing else registers here
 * yet; tracing arrives behind its flag with the system page.
 */
export const onRequestError: Instrumentation.onRequestError = (error, request, context) => {
  const message = error instanceof Error ? error.message : String(error);
  const digest =
    typeof error === "object" && error !== null && "digest" in error
      ? String((error as { digest: unknown }).digest)
      : undefined;
  const requestId = request.headers["x-request-id"];
  const line = {
    level: "error",
    event: "request_error",
    message,
    digest,
    path: request.path,
    method: request.method,
    route_path: context.routePath,
    route_type: context.routeType,
    correlation_id: Array.isArray(requestId) ? requestId[0] : requestId,
  };
  console.error(JSON.stringify(line));
};
