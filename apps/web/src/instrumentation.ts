import type { Instrumentation } from "next";

/**
 * Called once when a Next.js server starts. On the Node.js runtime it registers OpenTelemetry
 * behind the flag `web.otel_enabled` (server/telemetry.ts): off by default, and exporting spans
 * only when an OTLP endpoint is configured. The edge runtime registers nothing.
 */
export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  const { registerTelemetry } = await import("./server/telemetry");
  await registerTelemetry();
}

/**
 * Server errors as one JSON line on stderr, keyed so a log search finds them: the digest the
 * error page shows, the route, and the request id we received.
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
