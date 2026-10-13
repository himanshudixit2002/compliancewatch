import "server-only";

import type { SessionClaims } from "@/entities/session/types";
import { readMe, type SessionDeps } from "@/server/auth/sessions";
import { signedOut } from "@/server/auth/signed-out";
import type { ApiError } from "@/server/result";

/**
 * The account page's read of `GET /v1/identity/me` with the session's token: the profile
 * fields the cookie does not carry (email, phone, the tenant's name). A revoked session ends
 * on the sign-in page; an identity that reads no token (header mode) or does not answer
 * leaves the page to the session's facts, with the reason.
 */
export interface AccountProfile {
  email: string;
  phone: string;
  tenantName: string;
  tenantStatus: string;
}

export type AccountRead =
  | { kind: "profile"; profile: AccountProfile }
  | { kind: "unverifiable" }
  | { kind: "error"; error: ApiError };

export async function getAccount(
  session: SessionClaims,
  deps: SessionDeps = {},
): Promise<AccountRead> {
  const read = await readMe(session, deps);
  switch (read.kind) {
    case "ok":
      return {
        kind: "profile",
        profile: {
          email: read.me.email,
          phone: read.me.phone,
          tenantName: read.me.tenant.name,
          tenantStatus: read.me.tenant.status,
        },
      };
    case "revoked":
      return signedOut();
    case "unverifiable":
      return { kind: "unverifiable" };
    case "failed":
      return { kind: "error", error: read.error };
  }
}
