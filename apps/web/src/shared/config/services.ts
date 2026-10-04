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

/**
 * Services whose OpenAPI spec is committed under packages/contracts/openapi. This module has no
 * file access, so the list is written out; screens.test.ts fails when it and the directory's
 * `*.v1.json` files differ, so a newly committed spec is added here before the registry rules
 * see its routes. public.v1.json is not a service: it merges the operations the services tag
 * public, and each of those is also in its own service's spec.
 */
export const SERVICES_WITH_SPECS: readonly ServiceName[] = [
  "identity",
  "profile",
  "rulebook",
  "applicability-engine",
  "obligation",
  "notification",
  "qa",
  "llm-gateway",
  "eval",
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

/** The key of a route that requires a request header: `service METHOD path [header name]`. */
export function requiredHeaderKey(
  route: Pick<RouteRef, "service" | "method" | "path">,
  header: string,
): string {
  return `${routeKey(route)} [header ${header.toLowerCase()}]`;
}

/**
 * The key an awaited route lands under: its route key, or, for a route awaited in a hardened
 * form, the key of the route requiring that header. A set of committed keys holds both kinds.
 */
export function awaitKey(
  route: Pick<RouteRef, "service" | "method" | "path"> & { header?: string },
): string {
  return route.header === undefined ? routeKey(route) : requiredHeaderKey(route, route.header);
}
