import { randomUUID } from "node:crypto";
import { MFA_REQUIRED_ROLES } from "@/shared/config/roles";
import type { Role, TenantKind } from "@/shared/config/roles";
import { jsonResponse, problemResponse, type FakeFetch, type RecordedRequest } from "./fake-fetch";

/**
 * A stand-in for the identity service's sign-in routes, for tests of the adapters, the
 * exchange, the actions and the handlers: the development provider tokens (with personas),
 * the session exchange, sign-up, /me and the user routes, over the fake-fetch recorder, with
 * the refusals identity answers (not provisioned, mfa required, disabled, revoked, last admin,
 * role not allowed, subject registered). Tokens are unsigned JWT-shaped strings: the web never
 * verifies one, identity does, and here the fixture is identity.
 */
export interface FixtureTenant {
  id: string;
  kind: TenantKind;
  name: string;
  status: "active" | "deletion_requested";
}

export interface FixtureUser {
  id: string;
  tenantId: string;
  subject: string;
  email: string;
  phone: string;
  displayName: string;
  roles: Role[];
  status: "active" | "disabled";
  sessionVersion: number;
}

export interface IdentityFixture extends FakeFetch {
  tenants: Map<string, FixtureTenant>;
  users: Map<string, FixtureUser>;
  /** A provider token for the contact, as the dev route would sign it. */
  providerToken(contact: { email?: string; phone?: string }, aal?: "aal1" | "aal2"): string;
  /** Makes a user exist, as a persona or an invitation would. */
  provision(input: {
    contact: { email?: string; phone?: string };
    kind: TenantKind;
    roles: Role[];
    displayName?: string;
    tenantId?: string;
  }): FixtureUser;
  /** The CW access token identity would mint for the user now. */
  accessToken(user: FixtureUser): string;
  /** Changes a user's roles or disables it, bumping the session version. */
  bump(userId: string, change: { roles?: Role[]; disabled?: boolean }): void;
  /** Identity in header mode: /me and the user routes read no token. */
  headerMode: boolean;
}

const ACCESS_PREFIX = "cw";
const ACCESS_TTL = 600;

function base64url(value: unknown): string {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

export function unsignedJwt(claims: Record<string, unknown>): string {
  return `${base64url({ alg: "none", typ: "JWT" })}.${base64url(claims)}.sig`;
}

export function claimsOf(token: string): Record<string, unknown> | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    return JSON.parse(Buffer.from(parts[1] as string, "base64url").toString()) as Record<
      string,
      unknown
    >;
  } catch {
    return null;
  }
}

function subjectFor(contact: { email?: string; phone?: string }): string {
  return `subject:${contact.phone ?? contact.email ?? ""}`;
}

function problem(status: number, slug: string, detail?: string): Response {
  return problemResponse(status, {
    type: `urn:compliancewatch:problem:${slug}`,
    title: slug,
    ...(detail === undefined ? {} : { detail }),
  });
}

export function fakeIdentity(
  options: { headerMode?: boolean; now?: () => number } = {},
): IdentityFixture {
  const tenants = new Map<string, FixtureTenant>();
  const users = new Map<string, FixtureUser>();
  const requests: RecordedRequest[] = [];
  const now = options.now ?? (() => Math.floor(Date.now() / 1000));
  const fixture: IdentityFixture = {
    tenants,
    users,
    requests,
    headerMode: options.headerMode ?? false,
    fetchImpl: async () => new Response(null, { status: 500 }),
    providerToken(contact, aal = "aal1") {
      return unsignedJwt({
        iss: "urn:compliancewatch:fake-identity-provider",
        sub: subjectFor(contact),
        email: contact.email ?? "",
        phone: contact.phone ?? "",
        aal,
        iat: now(),
        exp: now() + 3600,
      });
    },
    provision(input) {
      const subject = subjectFor(input.contact);
      const existing = [...users.values()].find((user) => user.subject === subject);
      if (existing !== undefined) return existing;
      const tenantId = input.tenantId ?? randomUUID();
      if (!tenants.has(tenantId)) {
        tenants.set(tenantId, {
          id: tenantId,
          kind: input.kind,
          name: `Development ${input.kind} (synthetic)`,
          status: "active",
        });
      }
      const user: FixtureUser = {
        id: randomUUID(),
        tenantId,
        subject,
        email: input.contact.email ?? "",
        phone: input.contact.phone ?? "",
        displayName: input.displayName ?? "",
        roles: [...input.roles],
        status: "active",
        sessionVersion: 0,
      };
      users.set(user.id, user);
      return user;
    },
    accessToken(user) {
      return `${ACCESS_PREFIX}.${user.id}.${user.sessionVersion}`;
    },
    bump(userId, change) {
      const user = users.get(userId);
      if (user === undefined) throw new Error(`no user ${userId}`);
      if (change.roles !== undefined) user.roles = [...change.roles];
      if (change.disabled) user.status = "disabled";
      user.sessionVersion += 1;
    },
  };

  const tenantOut = (tenant: FixtureTenant) => ({
    id: tenant.id,
    kind: tenant.kind,
    name: tenant.name,
    region: "in",
    status: tenant.status,
    created_at: "2000-04-10T05:00:00Z",
  });
  const userOut = (user: FixtureUser) => ({
    id: user.id,
    tenant_id: user.tenantId,
    email: user.email,
    phone: user.phone,
    display_name: user.displayName,
    roles: [...user.roles].sort(),
    status: user.status,
    session_version: user.sessionVersion,
    created_at: "2000-04-10T05:00:00Z",
    updated_at: "2000-04-10T05:00:00Z",
  });
  const sessionOut = (user: FixtureUser, tenant: FixtureTenant, mfa: boolean) => ({
    access_token: fixture.accessToken(user),
    token_type: "Bearer",
    expires_in: ACCESS_TTL,
    tenant_id: tenant.id,
    tenant_kind: tenant.kind,
    user_id: user.id,
    display_name: user.displayName,
    roles: [...user.roles].sort(),
    mfa,
    session_version: user.sessionVersion,
  });

  /** The user a bearer names, or the refusal. */
  const bearerUser = (request: RecordedRequest): FixtureUser | Response => {
    if (fixture.headerMode) return problem(401, "auth-token-required");
    const header = request.headers.authorization ?? "";
    if (!header.startsWith("Bearer ")) return problem(401, "auth-token-required");
    const [prefix, userId, version] = header.slice("Bearer ".length).split(".");
    const user = userId === undefined ? undefined : users.get(userId);
    if (prefix !== ACCESS_PREFIX || user === undefined) return problem(401, "auth-token-invalid");
    if (user.status !== "active" || String(user.sessionVersion) !== version) {
      return problem(401, "identity-session-revoked");
    }
    return user;
  };

  const exchange = (token: string): Response => {
    const claims = claimsOf(token);
    if (claims === null || typeof claims.sub !== "string") {
      return problem(401, "identity-provider-token-invalid");
    }
    const user = [...users.values()].find((candidate) => candidate.subject === claims.sub);
    if (user === undefined) return problem(404, "identity-user-not-provisioned");
    const tenant = tenants.get(user.tenantId);
    if (tenant === undefined) return problem(404, "identity-user-not-provisioned");
    if (tenant.status === "deletion_requested") return problem(403, "identity-tenant-deleting");
    if (user.status !== "active") return problem(403, "identity-user-disabled");
    const mfa = claims.aal === "aal2";
    if (user.roles.some((role) => MFA_REQUIRED_ROLES.includes(role)) && !mfa) {
      return problem(403, "identity-mfa-required");
    }
    return jsonResponse(200, sessionOut(user, tenant, mfa));
  };

  fixture.fetchImpl = async (input, init) => {
    const raw = input;
    const url = new URL(raw.url);
    const text = await raw.text();
    const headers: Record<string, string> = {};
    raw.headers.forEach((value, key) => {
      headers[key] = value;
    });
    let body: Record<string, unknown> = {};
    if (text !== "") {
      try {
        body = JSON.parse(text) as Record<string, unknown>;
      } catch {
        body = {};
      }
    }
    const request: RecordedRequest = {
      method: raw.method,
      url: raw.url,
      pathname: url.pathname,
      headers,
      body,
      cache: raw.cache,
      ...(init?.next === undefined ? {} : { next: init.next }),
    };
    requests.push(request);
    const path = url.pathname;
    if (request.method === "POST" && path === "/v1/identity/dev/provider-tokens") {
      const contact = {
        ...(typeof body.email === "string" ? { email: body.email.toLowerCase() } : {}),
        ...(typeof body.phone === "string" ? { phone: body.phone } : {}),
      };
      if (contact.email === undefined && contact.phone === undefined) {
        return problem(422, "validation-error");
      }
      let made: FixtureUser | undefined;
      if (typeof body.tenant_kind === "string" && Array.isArray(body.roles)) {
        made = fixture.provision({
          contact,
          kind: body.tenant_kind as TenantKind,
          roles: body.roles as Role[],
          displayName: typeof body.display_name === "string" ? body.display_name : "",
          ...(typeof body.tenant_id === "string" ? { tenantId: body.tenant_id } : {}),
        });
      }
      const aal = body.aal === "aal2" ? "aal2" : "aal1";
      return jsonResponse(200, {
        provider_token: fixture.providerToken(contact, aal),
        subject: subjectFor(contact),
        tenant_id: made?.tenantId ?? null,
        user_id: made?.id ?? null,
      });
    }
    if (request.method === "POST" && path === "/v1/identity/sessions") {
      return exchange(String(body.provider_token ?? ""));
    }
    if (request.method === "POST" && path === "/v1/identity/tenants") {
      const claims = claimsOf(String(body.provider_token ?? ""));
      if (claims === null || typeof claims.sub !== "string") {
        return problem(401, "identity-provider-token-invalid");
      }
      if ([...users.values()].some((user) => user.subject === claims.sub)) {
        return problem(409, "identity-subject-registered");
      }
      const kind = body.kind === "ca_firm" ? "ca_firm" : "business";
      if (kind === "ca_firm" && claims.aal !== "aal2") return problem(403, "identity-mfa-required");
      const contact = {
        ...(typeof claims.email === "string" && claims.email !== "" ? { email: claims.email } : {}),
        ...(typeof claims.phone === "string" && claims.phone !== "" ? { phone: claims.phone } : {}),
      };
      const user = fixture.provision({
        contact,
        kind,
        roles: [kind === "ca_firm" ? "ca_admin" : "owner"],
        displayName: typeof body.display_name === "string" ? body.display_name : "",
      });
      const tenant = tenants.get(user.tenantId) as FixtureTenant;
      tenant.name = String(body.name ?? tenant.name);
      return jsonResponse(201, {
        tenant: tenantOut(tenant),
        user: userOut(user),
        session: sessionOut(user, tenant, claims.aal === "aal2"),
      });
    }
    if (request.method === "GET" && path === "/v1/identity/me") {
      const user = bearerUser(request);
      if (user instanceof Response) return user;
      const tenant = tenants.get(user.tenantId) as FixtureTenant;
      return jsonResponse(200, {
        kind: "user",
        user_id: user.id,
        tenant: tenantOut(tenant),
        roles: [...user.roles].sort(),
        session_version: user.sessionVersion,
        mfa: true,
        email: user.email,
        phone: user.phone,
        display_name: user.displayName,
      });
    }
    if (path === "/v1/identity/users" || path.startsWith("/v1/identity/users/")) {
      const admin = bearerUser(request);
      if (admin instanceof Response) return admin;
      const tenant = tenants.get(admin.tenantId) as FixtureTenant;
      const members = [...users.values()].filter((user) => user.tenantId === tenant.id);
      const admins = (list: FixtureUser[]) =>
        list.filter(
          (user) =>
            user.status === "active" &&
            user.roles.some((role) => ["owner", "ca_admin", "admin"].includes(role)),
        );
      const allowed: Record<TenantKind, Role[]> = {
        business: ["owner", "staff", "compliance_lead"],
        ca_firm: ["ca_admin", "ca_staff", "compliance_lead"],
        internal: ["analyst", "reviewer", "admin"],
      };
      if (request.method === "GET" && path === "/v1/identity/users") {
        return jsonResponse(200, { items: members.map(userOut) });
      }
      if (request.method === "POST" && path === "/v1/identity/users") {
        const roles = Array.isArray(body.roles) ? (body.roles as Role[]) : [];
        const refused = roles.filter((role) => !allowed[tenant.kind].includes(role));
        if (roles.length === 0 || refused.length > 0) {
          return problem(
            422,
            "identity-role-not-allowed",
            `a ${tenant.kind} tenant has no role ${refused.join(", ")}`,
          );
        }
        const contact = {
          ...(typeof body.email === "string" ? { email: body.email } : {}),
          ...(typeof body.phone === "string" ? { phone: body.phone } : {}),
        };
        if ([...users.values()].some((user) => user.subject === subjectFor(contact))) {
          return problem(409, "identity-provider-account-exists");
        }
        const invited = fixture.provision({
          contact,
          kind: tenant.kind,
          roles,
          displayName: typeof body.display_name === "string" ? body.display_name : "",
          tenantId: tenant.id,
        });
        return jsonResponse(201, userOut(invited));
      }
      const match = /^\/v1\/identity\/users\/([^/]+)\/(roles|disable)$/.exec(path);
      const target = match === null ? undefined : users.get(match[1] as string);
      if (match === null || target === undefined || target.tenantId !== tenant.id) {
        return problem(404, "identity-user-not-found");
      }
      if (match[2] === "roles" && request.method === "PUT") {
        const roles = Array.isArray(body.roles) ? (body.roles as Role[]) : [];
        const refused = roles.filter((role) => !allowed[tenant.kind].includes(role));
        if (roles.length === 0 || refused.length > 0) {
          return problem(
            422,
            "identity-role-not-allowed",
            `a ${tenant.kind} tenant has no role ${refused.join(", ")}`,
          );
        }
        if (target.status !== "active") return problem(403, "identity-user-disabled");
        const keepsAdmin = roles.some((role) => ["owner", "ca_admin", "admin"].includes(role));
        if (!keepsAdmin && admins(members).length === 1 && admins(members)[0]?.id === target.id) {
          return problem(409, "identity-last-admin");
        }
        if (roles.slice().sort().join() !== target.roles.slice().sort().join()) {
          fixture.bump(target.id, { roles });
        }
        return jsonResponse(200, userOut(target));
      }
      if (match[2] === "disable" && request.method === "POST") {
        if (target.status === "active") {
          if (admins(members).length === 1 && admins(members)[0]?.id === target.id) {
            return problem(409, "identity-last-admin");
          }
          fixture.bump(target.id, { disabled: true });
        }
        return jsonResponse(200, userOut(target));
      }
    }
    return problem(404, "web-test-no-route", `${request.method} ${path}`);
  };
  return fixture;
}
