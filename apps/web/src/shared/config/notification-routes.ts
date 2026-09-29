import type { RouteRef } from "./services.ts";

/**
 * The notification service has no committed OpenAPI spec yet; this list mirrors
 * services/notification/src/notification/api/router.py by hand and is the registry test's
 * source of truth for that service until notification.v1.json lands under packages/contracts.
 */
export const NOTIFICATION_ROUTES: readonly RouteRef[] = [
  { service: "notification", method: "GET", path: "/health" },
  { service: "notification", method: "GET", path: "/ready" },
  { service: "notification", method: "GET", path: "/v1/notification/ping" },
  {
    service: "notification",
    method: "PUT",
    path: "/v1/notification/preferences/{channel}/{recipient}",
  },
  {
    service: "notification",
    method: "GET",
    path: "/v1/notification/preferences/{channel}/{recipient}",
  },
  { service: "notification", method: "POST", path: "/v1/notification/send" },
  { service: "notification", method: "GET", path: "/v1/notification/templates" },
];
