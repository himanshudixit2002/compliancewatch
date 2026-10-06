import "server-only";

import { roleLabels } from "@/entities/screen/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { signInHref } from "@/shared/config/nav";
import { REGULATORY_ROLES, hasRole, isRegulatory } from "@/shared/config/roles";
import type { Screen } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { verifySession } from "../dal";
import { getEnv } from "../env";
import { isSameOriginRequest } from "../origin";
import { problemResponse } from "./problem";

/**
 * The gate every BFF route handler (each `route.ts` under `app/api-bff/`) runs first, with its own
 * registry entry, before it reads a parameter or a byte of the body; handler-gate.test.ts holds
 * every such file to it. The proxy is left off `/api-bff/` (D-059), so nothing else checks these
 * requests on the way in, and the checks are the registry's, as a page's gate (server/dal.ts)
 * takes them:
 *
 * - a method that writes (anything but GET and HEAD) from another site is refused (403) before the
 *   session is read: the sign-out handler's origin check (`server/origin.ts`), which reads
 *   `X-Forwarded-Host` only when CW_WEB_TRUST_FORWARDED_IP says the proxy is trusted;
 * - without a session, a GET (a link the browser follows, such as a stored file opened in a new
 *   tab) goes to the sign-in page and comes back; any other method is a 401 problem;
 * - a session holding none of the entry's roles is a 404 when the entry is for regulatory roles
 *   only and the session holds none (the admin tools' answer to a tenant role: the tool does not
 *   exist for it), and otherwise a 403 that names the roles; a tenant kind the entry does not list
 *   is a 403 too.
 *
 * What the proxy will also do for pages once identity issues tokens (refreshing a token about to
 * expire, re-reading /me, ending a session whose version is stale, the /admin allow-list) these
 * handlers will do here, since the proxy never sees them.
 */
export type HandlerGate = { ok: true; session: SessionClaims } | { ok: false; response: Response };

const READS: ReadonlySet<string> = new Set(["GET", "HEAD"]);

function refused(response: Response): HandlerGate {
  return { ok: false, response };
}

/** The session of a request the entry's roles may make, or the answer that refuses it. */
export async function gateHandler(screen: Screen, request: Request): Promise<HandlerGate> {
  if (screen.kind !== "handler" || screen.roles === "public") {
    throw new Error(`${screen.id}: the handler gate takes a handler entry that names its roles`);
  }
  const reads = READS.has(request.method.toUpperCase());
  if (!reads) {
    const trustForwardedHost = getEnv().CW_WEB_TRUST_FORWARDED_IP;
    if (!isSameOriginRequest(request.headers, { trustForwardedHost })) {
      return refused(
        problemResponse({
          slug: "web-cross-origin-request",
          status: 403,
          title: t("handlers.crossOrigin"),
          detail: t("handlers.crossOriginDetail"),
        }),
      );
    }
  }
  const session = await verifySession();
  if (session === null) {
    if (reads) {
      const { pathname } = new URL(request.url);
      return refused(
        new Response(null, { status: 303, headers: { location: signInHref(pathname) } }),
      );
    }
    return refused(
      problemResponse({
        slug: "web-sign-in-required",
        status: 401,
        title: t("handlers.signIn"),
        detail: t("handlers.signInDetail"),
      }),
    );
  }
  const kindAllowed =
    screen.tenantKinds === undefined || screen.tenantKinds.includes(session.tenantKind);
  if (hasRole(session, screen.roles) && kindAllowed) return { ok: true, session };
  const regulatoryOnly = screen.roles.every((role) => REGULATORY_ROLES.includes(role));
  if (regulatoryOnly && !isRegulatory(session)) {
    return refused(
      problemResponse({ slug: "web-not-found", status: 404, title: t("handlers.notFound") }),
    );
  }
  return refused(
    problemResponse({
      slug: "web-role-required",
      status: 403,
      title: t("handlers.roleRequired"),
      detail: t("handlers.roleRequiredDetail", { roles: roleLabels(screen.roles).join(", ") }),
    }),
  );
}
