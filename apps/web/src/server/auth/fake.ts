import "server-only";

import { createHash, randomUUID } from "node:crypto";
import { sessionWindow } from "@/entities/session/mappers";
import type { SessionClaims } from "@/entities/session/types";
import { ALLOWED_ROLES, ROLES, isRole, isTenantKind, requiresMfa } from "@/shared/config/roles";
import type { Role, TenantKind } from "@/shared/config/roles";
import { isUuid } from "@/shared/lib/identifiers";
import { EnvError, isLocalOrTest, type WebEnv } from "../env";
import { err, ok, webError, type Result } from "../result";
import type {
  AuthProvider,
  CompleteSignInInput,
  FakeSignInInput,
  SignInChallenge,
  SignInContext,
  SignInMethod,
} from "./provider";

/**
 * The development sign-in: no password, no provider, no service. The form picks a tenant (an
 * existing id, or a new one), its kind, one or more of the roles that kind allows, and a
 * display name; the adapter mints the claims the cookie will carry. It exists only where
 * CW_WEB_ENV is local or test: the environment module refuses the value elsewhere and the
 * constructor refuses again.
 *
 * What is fake, and documented as such: the second factor is asserted (`mfa: true`) for the
 * roles that need one, since nothing was verified; the session version is 1; the user id is a
 * name-based UUID of the tenant and the display name, so signing in again with the same name
 * in the same tenant is the same user, which keeps `decided_by` and `recorded_by` stable
 * across a local session's life.
 */
export const FAKE_METHODS: readonly SignInMethod[] = ["fake"];

export const DISPLAY_NAME_MAX_LENGTH = 80;

/** RFC 4122 name-based UUID (version 5, SHA-1). */
export function uuidV5(namespace: string, name: string): string {
  const namespaceBytes = Buffer.from(namespace.replace(/-/g, ""), "hex");
  const hash = createHash("sha1").update(namespaceBytes).update(name, "utf8").digest();
  const bytes = Buffer.from(hash.subarray(0, 16));
  bytes[6] = ((bytes[6] as number) & 0x0f) | 0x50;
  bytes[8] = ((bytes[8] as number) & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** The URL namespace of RFC 4122; the name is the tenant and the normalised display name. */
const USER_NAMESPACE = "6ba7b811-9dad-11d1-80b4-00c04fd430c8";

export function fakeUserId(tenantId: string, displayName: string): string {
  const name = `compliancewatch:fake-user:${tenantId}:${displayName.trim().toLowerCase()}`;
  return uuidV5(USER_NAMESPACE, name);
}

/** The roles in the registry's order, without duplicates. */
function normaliseRoles(roles: readonly Role[]): Role[] {
  return ROLES.filter((role) => roles.includes(role));
}

/** Checks the input the way the identity service would, naming each field that fails. */
export function validateFakeSignIn(input: FakeSignInInput): Record<string, string[]> {
  const errors: Record<string, string[]> = {};
  const displayName = input.displayName.trim();
  if (displayName === "") errors.displayName = ["Enter a display name."];
  else if (displayName.length > DISPLAY_NAME_MAX_LENGTH) {
    errors.displayName = [`Use at most ${DISPLAY_NAME_MAX_LENGTH} characters.`];
  }
  const tenantId = input.tenantId?.trim() ?? "";
  if (tenantId !== "" && !isUuid(tenantId)) errors.tenantId = ["Enter a UUID, or leave it empty."];
  if (!isTenantKind(input.tenantKind)) {
    errors.tenantKind = ["Choose a tenant kind."];
    return errors;
  }
  const allowed = ALLOWED_ROLES[input.tenantKind];
  const unknown = input.roles.filter((role) => !isRole(role));
  const disallowed = input.roles.filter((role) => isRole(role) && !allowed.includes(role));
  if (input.roles.length === 0) errors.roles = ["Choose at least one role."];
  else if (unknown.length > 0) errors.roles = [`Unknown role: ${unknown.join(", ")}.`];
  else if (disallowed.length > 0) {
    errors.roles = [
      `A ${input.tenantKind} tenant cannot hold ${disallowed.join(", ")}; it allows ${allowed.join(", ")}.`,
    ];
  }
  return errors;
}

/** The claims for a valid fake sign-in; a validation error otherwise. Pure, given the clock. */
export function mintFakeSession(
  input: FakeSignInInput,
  context: SignInContext,
): Result<SessionClaims> {
  const errors = validateFakeSignIn(input);
  if (Object.keys(errors).length > 0) {
    return err(
      webError(
        "validation",
        "web-fake-sign-in-invalid",
        "Check the sign-in details",
        undefined,
        errors,
      ),
    );
  }
  const tenantId = input.tenantId?.trim() || randomUUID();
  const displayName = input.displayName.trim();
  const roles = normaliseRoles(input.roles);
  return ok({
    userId: fakeUserId(tenantId, displayName),
    tenantId,
    tenantKind: input.tenantKind as TenantKind,
    roles,
    displayName,
    mfa: requiresMfa(roles),
    sv: 1,
    provider: "fake",
    ...sessionWindow(context.now, context.ttlSeconds),
  });
}

export class FakeAuthProvider implements AuthProvider {
  readonly name = "fake";
  readonly methods = FAKE_METHODS;

  constructor(env: WebEnv) {
    if (!isLocalOrTest(env.CW_WEB_ENV)) {
      throw new EnvError(
        `the fake sign-in provider is refused when CW_WEB_ENV is ${env.CW_WEB_ENV}; local and test only`,
      );
    }
  }

  startSignIn(): Promise<Result<SignInChallenge>> {
    return Promise.resolve(
      err(
        webError(
          "bad_request",
          "web-fake-provider-no-challenge",
          "The fake provider has no challenge step",
          "Complete the sign-in directly with a tenant, kind, roles and display name.",
        ),
      ),
    );
  }

  completeSignIn(
    input: CompleteSignInInput,
    context: SignInContext,
  ): Promise<Result<SessionClaims>> {
    if (input.kind !== "fake") {
      return Promise.resolve(
        err(
          webError(
            "bad_request",
            "web-fake-provider-input",
            "The fake provider takes only a fake sign-in",
            `A ${input.kind} sign-in needs the identity provider adapter.`,
          ),
        ),
      );
    }
    return Promise.resolve(mintFakeSession(input, context));
  }

  signOut(): Promise<void> {
    return Promise.resolve();
  }
}
