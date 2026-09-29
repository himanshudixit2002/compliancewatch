/**
 * The services the web app talks to, named as their OpenAPI files and Makefile entries are.
 * The order is the Makefile's SERVICES order (identity 8001 ... pipeline 8010).
 */
export const SERVICE_NAMES = [
  "identity",
  "profile",
  "rulebook",
  "applicability-engine",
  "obligation",
  "notification",
  "qa",
  "llm-gateway",
  "eval",
  "pipeline",
] as const;

export type ServiceName = (typeof SERVICE_NAMES)[number];

export const HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;

export type HttpMethod = (typeof HTTP_METHODS)[number];

/** A route on a service, written as its OpenAPI path template. */
export interface RouteRef {
  service: ServiceName;
  method: HttpMethod;
  path: string;
}

/** Services whose OpenAPI spec is committed under packages/contracts/openapi. */
export const SERVICES_WITH_SPECS: readonly ServiceName[] = [
  "identity",
  "profile",
  "rulebook",
  "obligation",
  "notification",
  "qa",
  "llm-gateway",
];

export function isServiceName(value: string): value is ServiceName {
  return (SERVICE_NAMES as readonly string[]).includes(value);
}

/** `/v1/x/{node_id}` and `/v1/x/{id}` are the same template: parameter names do not matter. */
export function normalisePath(path: string): string {
  return path.replace(/\{[^}]*\}/g, "{}");
}

export function routeKey(route: Pick<RouteRef, "service" | "method" | "path">): string {
  return `${route.service} ${route.method} ${normalisePath(route.path)}`;
}
