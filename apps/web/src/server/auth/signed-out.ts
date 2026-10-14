import "server-only";

import { redirect } from "next/navigation";
import { signedOutHref } from "@/shared/config/nav";

/**
 * Ends the request on the sign-in page because identity no longer knows the session: a 401
 * `auth-token-invalid` from any service, or `identity-session-revoked` from identity (a bumped
 * session version after a change of roles, a disabled user). A render cannot clear a cookie,
 * so the proxy does it on the way to `/sign-in?reason=signed-out` (src/proxy.ts), and the
 * sign-in page says the session ended.
 */
export function signedOut(): never {
  redirect(signedOutHref());
}
