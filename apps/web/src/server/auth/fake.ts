import "server-only";

import { createHash, randomUUID } from "node:crypto";
import type { identity } from "@compliancewatch/contracts/openapi";
import { epochSeconds } from "@/entities/session/mappers";
import { ALLOWED_ROLES, ROLES, isRole, isTenantKind, requiresMfa } from "@/shared/config/roles";
import type { Role } from "@/shared/config/roles";
import { isE164, isEmailAddress, isUuid } from "@/shared/lib/identifiers";
import { call, createServiceClient, type FetchImpl } from "../api/client";
import { EnvError, isLocalOrTest, serviceUrl, type WebEnv } from "../env";
import { err, isProblem, ok, type ApiError, type Result } from "../result";
import {
  providerFailure,
  type Aal,
  type AuthProvider,
  type DevPersonaInput,
  type EmailLinkSent,
  type MfaChallenge,
  type MfaFactor,
  type MfaPort,
  type ProviderSession,
  type SignInMethod,
} from "./provider";

/**
 * The development adapter: identity's fake provider, through `POST /v1/identity/dev/provider-tokens`,
 * which identity serves only with its own fake provider in local and test. Nothing is sent to
 * anyone, so every step that would wait for a person is short: any six-digit code passes the
 * OTP step, the email link is handed back to be opened instead of mailed (`devLink`), the
 * second factor is asserted by one confirm (the route signs a token at aal2), and the
 * development sign-in form's persona (a tenant kind, roles, a name and an optional tenant id)
 * is made by identity on the spot, so the token exchanges for a session like any other.
 *
 * What is fake, and documented as such on the account page: the second factor is asserted,
 * never verified. What is real: identity issues the session, keeps the user, and revokes it
 * like anyone's. A persona's contact is a synthetic address derived from the tenant and the
 * name (`personaEmail`), so signing in again with the same name in the same tenant is the
 * same user, which keeps `decided_by` and `recorded_by` stable across a local session's life.
 * The adapter exists only where CW_WEB_ENV is local or test: the environment module refuses
 * the value elsewhere and the constructor refuses again.
 */
export const FAKE_METHODS: readonly SignInMethod[] = ["dev", "phone", "email"];

export const DISPLAY_NAME_MAX_LENGTH = 80;

/** A reserved domain (RFC 2606): no mail ever goes there, and no real address lives there. */
export const PERSONA_EMAIL_DOMAIN = "fake.compliancewatch.invalid";

/** The one factor the confirm step stands for. */
export const FAKE_FACTOR_ID = "fake-confirm";

const OTP_CODE = /^[0-9]{6}$/;
const FAKE_TOKEN_TTL_SECONDS = 3_600;
const REFRESH_PREFIX = "fake.v1.";

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

/** A stable id for a persona: the same name in the same tenant is the same person. */
export function fakeUserId(tenantId: string, displayName: string): string {
  const name = `compliancewatch:fake-user:${tenantId}:${displayName.trim().toLowerCase()}`;
  return uuidV5(USER_NAMESPACE, name);
}

/** The synthetic address a persona signs in with; identity's subject derives from it. */
export function personaEmail(tenantId: string, displayName: string): string {
  return `${fakeUserId(tenantId, displayName)}@${PERSONA_EMAIL_DOMAIN}`;
}

/** The roles in the registry's order, without duplicates. */
function normaliseRoles(roles: readonly Role[]): Role[] {
  return ROLES.filter((role) => roles.includes(role));
}

/** Checks the persona the way the identity service would, naming each field that fails. */
export function validateFakeSignIn(input: DevPersonaInput): Record<string, string[]> {
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

/** The contact a fake token or refresh token names. */
export interface FakeContact {
  phone?: string;
  email?: string;
}

interface FakeRefresh {
  contact: FakeContact;
  aal: Aal;
}

/** The refresh token of the fake adapter: the contact and the level to mint again with. */
export function encodeFakeRefreshToken(contact: FakeContact, aal: Aal): string {
  const json = JSON.stringify({ contact, aal } satisfies FakeRefresh);
  return `${REFRESH_PREFIX}${Buffer.from(json, "utf8").toString("base64url")}`;
}

export function decodeFakeRefreshToken(token: string): FakeRefresh | null {
  if (!token.startsWith(REFRESH_PREFIX)) return null;
  try {
    const parsed: unknown = JSON.parse(
      Buffer.from(token.slice(REFRESH_PREFIX.length), "base64url").toString("utf8"),
    );
    if (typeof parsed !== "object" || parsed === null) return null;
    const { contact, aal } = parsed as { contact?: unknown; aal?: unknown };
    if (aal !== "aal1" && aal !== "aal2") return null;
    if (typeof contact !== "object" || contact === null) return null;
    const { phone, email } = contact as { phone?: unknown; email?: unknown };
    const found: FakeContact = {};
    if (typeof phone === "string" && phone !== "") found.phone = phone;
    if (typeof email === "string" && email !== "") found.email = email;
    if (found.phone === undefined && found.email === undefined) return null;
    return { contact: found, aal };
  } catch {
    return null;
  }
}

/** The claims of a JWT, read without verifying it: identity is the only verifier. */
export function unverifiedClaims(token: string): Record<string, unknown> | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const parsed: unknown = JSON.parse(Buffer.from(parts[1] as string, "base64url").toString());
    return typeof parsed === "object" && parsed !== null
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

type DevTokenBody =
  identity.paths["/v1/identity/dev/provider-tokens"]["post"]["requestBody"]["content"]["application/json"];

export class FakeAuthProvider implements AuthProvider {
  readonly name = "fake";
  readonly methods = FAKE_METHODS;
  readonly mfaMode = "confirm";
  readonly mfa: MfaPort;
  private readonly client;

  constructor(env: WebEnv, deps: { fetchImpl?: FetchImpl } = {}) {
    if (!isLocalOrTest(env.CW_WEB_ENV)) {
      throw new EnvError(
        `the fake sign-in provider is refused when CW_WEB_ENV is ${env.CW_WEB_ENV}; local and test only`,
      );
    }
    this.client = createServiceClient<identity.paths>({
      service: "identity",
      baseUrl: serviceUrl("identity", env),
      timeoutMs: env.CW_WEB_REQUEST_TIMEOUT_MS,
      fetchImpl: deps.fetchImpl,
    });
    this.mfa = {
      listFactors: () => Promise.resolve(ok<MfaFactor[]>([])),
      enrolTotp: () =>
        Promise.resolve(
          err(
            providerFailure(
              "unsupported",
              "The development sign-in has no authenticator app to enrol; confirm instead.",
            ),
          ),
        ),
      challenge: () =>
        Promise.resolve(
          ok<MfaChallenge>({
            challengeId: FAKE_FACTOR_ID,
            expiresAt: epochSeconds(new Date()) + 300,
          }),
        ),
      verify: (session) => this.assertSecondFactor(session),
      remove: () =>
        Promise.resolve(
          err(providerFailure("unsupported", "The development sign-in has no factor to remove.")),
        ),
    };
  }

  startPhoneOtp(phone: string): Promise<Result<void>> {
    if (!isE164(phone)) return Promise.resolve(err(invalidContact("phone")));
    return Promise.resolve(ok(undefined));
  }

  verifyPhoneOtp(phone: string, code: string): Promise<Result<ProviderSession>> {
    if (!isE164(phone)) return Promise.resolve(err(invalidContact("phone")));
    if (!OTP_CODE.test(code.replace(/\s/g, ""))) {
      return Promise.resolve(
        err(
          providerFailure("invalid_code", "The development sign-in takes any six digits.", {
            fieldErrors: { code: ["Enter the six digits."] },
          }),
        ),
      );
    }
    return this.mint({ phone }, "aal1");
  }

  async sendEmailLink(email: string, redirectTo: string): Promise<Result<EmailLinkSent>> {
    if (!isEmailAddress(email)) return err(invalidContact("email"));
    const minted = await this.mint({ email: email.trim().toLowerCase() }, "aal1");
    if (!minted.ok) return minted;
    const link = new URL(redirectTo);
    link.searchParams.set("token_hash", minted.value.accessToken);
    link.searchParams.set("type", "magiclink");
    return ok({ devLink: link.toString() });
  }

  exchangeEmailLink(tokenHash: string): Promise<Result<ProviderSession>> {
    const claims = unverifiedClaims(tokenHash);
    const contact = contactOf(claims);
    if (claims === null || contact === null) {
      return Promise.resolve(
        err(providerFailure("invalid_link", "The link does not carry a development token.")),
      );
    }
    return this.mint(contact, claims.aal === "aal2" ? "aal2" : "aal1");
  }

  refresh(refreshToken: string): Promise<Result<ProviderSession>> {
    const decoded = decodeFakeRefreshToken(refreshToken);
    if (decoded === null) {
      return Promise.resolve(
        err(providerFailure("expired", "The development refresh token is not readable.")),
      );
    }
    return this.mint(decoded.contact, decoded.aal);
  }

  /** Nothing to end: the fake provider keeps no session of its own. */
  signOut(): Promise<void> {
    return Promise.resolve();
  }

  signInAsPersona(input: DevPersonaInput): Promise<Result<ProviderSession>> {
    const errors = validateFakeSignIn(input);
    if (Object.keys(errors).length > 0) {
      return Promise.resolve(
        err(providerFailure("invalid_contact", undefined, { fieldErrors: errors })),
      );
    }
    const tenantId = input.tenantId?.trim() || randomUUID();
    const displayName = input.displayName.trim();
    const roles = normaliseRoles(input.roles);
    return this.mint(
      { email: personaEmail(tenantId, displayName) },
      requiresMfa(roles) ? "aal2" : "aal1",
      {
        tenant_id: tenantId,
        tenant_kind: input.tenantKind,
        roles,
        display_name: displayName,
      },
    );
  }

  /** The confirm step: the same person's token at aal2. */
  private assertSecondFactor(session: ProviderSession): Promise<Result<ProviderSession>> {
    const decoded = decodeFakeRefreshToken(session.refreshToken);
    if (decoded === null) {
      return Promise.resolve(
        err(providerFailure("expired", "The development session is not readable.")),
      );
    }
    return this.mint(decoded.contact, "aal2");
  }

  private async mint(
    contact: FakeContact,
    aal: Aal,
    persona: Pick<DevTokenBody, "tenant_id" | "tenant_kind" | "roles" | "display_name"> = {},
  ): Promise<Result<ProviderSession>> {
    const body: DevTokenBody = { aal, ...persona };
    if (contact.phone !== undefined) body.phone = contact.phone;
    if (contact.email !== undefined) body.email = contact.email;
    const result = await call(this.client.POST("/v1/identity/dev/provider-tokens", { body }));
    if (!result.ok) return err(mapMintError(result.error));
    const minted = result.value;
    if (minted === undefined || minted.provider_token === "") {
      return err(providerFailure("unavailable", "Identity answered without a token."));
    }
    const claims = unverifiedClaims(minted.provider_token);
    const exp = typeof claims?.exp === "number" ? claims.exp : undefined;
    return ok({
      accessToken: minted.provider_token,
      refreshToken: encodeFakeRefreshToken(contact, aal),
      expiresAt: exp ?? epochSeconds(new Date()) + FAKE_TOKEN_TTL_SECONDS,
      aal,
      subject: minted.subject,
    });
  }
}

function invalidContact(field: "phone" | "email"): ApiError {
  const message =
    field === "phone"
      ? "Enter a mobile number with its country code, such as +919876543210."
      : "Enter an email address.";
  return providerFailure("invalid_contact", undefined, { fieldErrors: { [field]: [message] } });
}

function contactOf(claims: Record<string, unknown> | null): FakeContact | null {
  if (claims === null) return null;
  const contact: FakeContact = {};
  if (typeof claims.phone === "string" && claims.phone !== "") contact.phone = claims.phone;
  if (typeof claims.email === "string" && claims.email !== "") contact.email = claims.email;
  return contact.phone === undefined && contact.email === undefined ? null : contact;
}

/** What a failure of the dev route means to the person at the form. */
function mapMintError(error: ApiError): ApiError {
  if (isProblem(error, "identity-dev-sign-in-unavailable")) {
    return providerFailure(
      "unavailable",
      "The identity service does not serve the development sign-in here: it needs CW_AUTH_PROVIDER=fake in local or test.",
    );
  }
  if (error.kind === "network" || error.kind === "server" || error.kind === "unavailable") {
    return providerFailure("unavailable", error.message);
  }
  // A persona identity refuses (a role the kind lacks, the last admin, another tenant) is the
  // service's own problem, shown as it is.
  return error;
}
