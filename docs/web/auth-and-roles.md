# Auth and roles

Who is asking, and what they may open. The session is an encrypted cookie the server writes
and reads ([ADR-019](../adr/ADR-019-web-server-layer-and-stateless-session.md)); the gates in
`server/dal.ts` decide every page, action and handler; the proxy only sends a visitor without a
cookie to the sign-in page first; sign-in goes through a provider port whose only adapter on
`main` is a development fake. How the server then calls the services on the user's behalf is in
[data-layer.md](data-layer.md).

## Roles and tenant kinds

`shared/config/roles.ts` holds the values, copied from the identity service's design (the
domain kernel's role list and the roles each tenant kind allows). `domain_kernel/access.py`
does not exist yet; when it does, a test parses it and compares the two, so they cannot drift.

| Role              | Tenant kind         | Sets                                   | Who                                               |
| ----------------- | ------------------- | -------------------------------------- | ------------------------------------------------- |
| `owner`           | business            | tenant member, tenant admin            | the business owner; first user of a business      |
| `staff`           | business            | tenant member                          | someone working in the business                   |
| `compliance_lead` | business or CA firm | tenant member                          | the person answerable for compliance              |
| `ca_admin`        | CA firm             | tenant member, tenant admin, needs MFA | runs the CA firm's account; first user of a firm  |
| `ca_staff`        | CA firm             | tenant member                          | works on the firm's clients                       |
| `analyst`         | internal            | regulatory, needs MFA                  | reads regulator documents, reviews candidates     |
| `reviewer`        | internal            | regulatory, needs MFA                  | approves and publishes                            |
| `admin`           | internal            | regulatory, needs MFA                  | runs the platform; first user of the internal org |

The sets are `TENANT_MEMBER_ROLES`, `TENANT_ADMIN_ROLES` (the last one of a tenant cannot be
removed), `REGULATORY_ROLES` (the only roles that open `/admin`) and `MFA_REQUIRED_ROLES`.
`ALLOWED_ROLES[kind]` lists the roles a user may hold in each tenant kind and `firstRoleFor(kind)`
the role a new tenant's first user gets. `hasRole`, `isRegulatory`, `requiresMfa` and
`tenantKindsFor` answer for a `Principal` (`{ roles, tenantKind? }`; the session claims are one).

Two places turn roles into access:

- **Screens.** A registry entry's `roles` (or `"public"`) and optional `tenantKinds` decide who
  may open it; `isVisibleTo` filters navigation and the sitemap with the same rule, and
  `docs/web/screens.md` has the generated role-by-screen matrix.
- **Capabilities.** `shared/config/permissions.ts` maps what an action asks for
  (`obligations.update_status`, `admin.publish`, `team.manage`, ...) to role lists, and
  `can(principal, capability)` answers. An action checks the capability; a screen checks its
  entry.

## The session

`cw_session` carries `SessionClaims` (`entities/session/types.ts`):

| Claim                    | Meaning                                                               | Fake provider                                  |
| ------------------------ | --------------------------------------------------------------------- | ---------------------------------------------- |
| `userId`                 | the user                                                              | name-based UUID of the tenant and display name |
| `tenantId`, `tenantKind` | the tenant the user acts in, and its kind                             | chosen on the form, or a new UUID              |
| `roles`                  | one or more roles the kind allows                                     | chosen on the form                             |
| `displayName`            | shown in the header and on `/account`; the only personal data carried | chosen on the form                             |
| `mfa`                    | whether a second factor was verified                                  | asserted `true` for MFA roles, not verified    |
| `sv`                     | identity's per-user session version; a bump revokes older sessions    | `1`                                            |
| `provider`               | `fake` or `supabase`                                                  | `fake`                                         |
| `issuedAt`, `expiresAt`  | seconds since the epoch                                               | now, and now plus the lifetime                 |

Five optional claims stay absent on `main`: `cwToken` and `cwTokenExpiresAt` (identity's token
for the services), `providerRefreshToken`, `checkedAt` (when `/me` was last re-read) and
`analyticsConsent`.

The cookie (`server/session.ts`):

- a compact JWE: `dir` key management, A256GCM, under `CW_WEB_SESSION_SECRET` (32 random bytes
  as base64: `openssl rand -base64 32`); the JWT's `iat` and `exp` are the claims' times;
- `httpOnly`, `SameSite=Lax`, `Secure` unless `CW_WEB_ENV` is `local` (browsers accept a Secure
  cookie from `http://localhost`, so the test environment works on plain HTTP), path `/`,
  `Max-Age` of `CW_WEB_SESSION_TTL_SECONDS` (28800, eight hours; at most a day);
- `decryptSession` answers `null` for anything that is not a valid, unexpired session under this
  key (tampered, truncated, another secret, expired, the wrong shape); a missing secret is a
  configuration error and throws, naming the variable. The secret is needed only where a
  session is encrypted or decrypted, so the build and the public pages run without it.

A cookie is written only by `setSessionCookie` and `clearSessionCookie`, which Next 16 allows
only in a server action or a route handler (the sign-in action and the sign-out handler); a page
or layout only reads. `sessionForRender()` gives shells and pages a `SessionDto` (the facts,
never a token field). Rotating the secret signs everyone out.

## The request path: proxy, then the gates

**`src/proxy.ts`** runs before a route renders (Next 16's proxy, Node runtime). Its matcher
skips `_next` assets, `/api/` and `/api-bff/` handlers and paths with a file extension (Next buffers
a request body for the proxy, which would cut an upload short; each `/api-bff/` handler gates
itself, D-059). For the rest,
`decide(pathname, search, hasCookie)` sends the visitor to `/sign-in?next=<path and query>`
when the path is under `/admin` or matches a registry page whose roles are not `"public"`, and
no `cw_session` cookie is present at all. It does not decrypt, check roles or write anything:
public pages, route handlers and unknown paths pass, and a cookie that is present but expired,
forged or short of the role is the gate's business. The proxy is not on a server action's path.

**`server/dal.ts`** is the authoritative gate. Each function reads the cookie through
`verifySession()`, which decrypts once per request (React `cache`).

| Gate                            | Answers                                                                                                        |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `verifySession()`               | the claims, or `null`                                                                                          |
| `requireSession({ next })`      | the claims, or a redirect to `/sign-in?next=`                                                                  |
| `requireRole(roles, { next })`  | the claims when a role matches; anonymous to sign-in, wrong role to `/forbidden`; `"public"`: optional session |
| `requireTenantKind(kinds)`      | the claims when the tenant kind matches, else `/forbidden`                                                     |
| `requireAdmin({ next })`        | a regulatory role, else `notFound()`: a tenant role must not learn that a tool exists                          |
| `requireScreen(screen, params)` | an entry's roles and tenant kinds; an admin entry through `requireAdmin`, 404 for a role it does not list      |
| `requireScreenSession(screen)`  | `requireScreen` for an entry that is never public                                                              |
| `sessionForRender()`            | the render-safe view, or `null`; for shells, never a decision                                                  |

Where they run: every `page.tsx` calls its gate on the first line (`/account` uses
`requireScreenSession`); the two catch-alls call `requireScreen` with the matched entry, so a
waiting screen is gated exactly like the live one it will become; the admin layout calls
`requireAdmin` (the outer wall: a tenant role gets the 404 before any admin markup exists) and
every admin page calls it again, because a layout does not re-run on every navigation; every
server action calls its gate again. The gates never write a cookie.

**Where a visitor lands.** `signInHref(next)` builds `/sign-in?next=` only for a same-origin
path worth returning to (not `/`, not the sign-in page itself). `safeNext(next, fallback)`
accepts only a path that starts with a single `/` and has no backslash, control character,
whitespace or scheme, so `next` cannot redirect off the site. After sign-in the visitor goes to
that path or to `homeFor(session)`: `/admin` for the regulatory roles, `/businesses` for every
tenant role. `forbiddenHref()` is `/forbidden`, a public page with a way out.

## Sign-in

**The port.** `server/auth/provider.ts` declares `AuthProvider`: `name`, the `methods` it
offers (`fake`, `phone`, `email`), `startSignIn(input)` (open a challenge: an OTP, an email
link), `completeSignIn(input, { now, ttlSeconds })` (answer the claims) and `signOut(claims)`.
Failures are `Result` errors with web-local problems. `providerFor(env)` picks the adapter
named by `CW_WEB_AUTH_PROVIDER`:

| Value      | Adapter                                                                                          |
| ---------- | ------------------------------------------------------------------------------------------------ |
| `fake`     | `server/auth/fake.ts`, local and test only                                                       |
| `supabase` | reserved; answers "Sign-in with supabase is not available yet" until the identity adapter exists |
| unset      | "Sign-in is not configured", naming the variable                                                 |

The sign-in page, the `signIn` action and the session module never name an adapter.

**The fake adapter.** The development sign-in has no password, no provider and no service
call. The form (`features/auth/ui/dev-sign-in-form.tsx`) asks for a tenant kind, one or more
roles the kind allows (the checkboxes follow the kind), a display name (at most 80
characters) and an optional tenant id (a UUID; empty mints a new tenant). "Use the last seeded
tenant" fills the tenant id from `var/seed/last.json` when `make web-seed` has written it.
`validateFakeSignIn` names each field that fails; `mintFakeSession` answers the claims: the user
id is a version 5 UUID of the tenant and the lower-cased display name, so the same name in the
same tenant is the same user across sign-ins (and `decided_by` stays stable); `mfa` is asserted
for the MFA roles and nothing is verified; `sv` is 1. It is refused twice outside `local` and
`test`: the environment schema rejects `CW_WEB_AUTH_PROVIDER=fake` there, and the adapter's
constructor refuses again (D-016).

**The flow.**

1. `/sign-in` (`app/(public)/sign-in/page.tsx`): a visitor who already has a session goes on to
   `next` or the role home; otherwise the page asks `providerFor` and renders the fake form, or
   the "not configured" state.
2. The `signIn` server action (`features/auth/actions.ts`) shape-checks the form
   (`parseFakeSignInForm`), asks the provider for the claims, writes the cookie and redirects to
   `safeNext(next, homeFor(session))`. Every expected failure comes back as an `ActionState`
   with field errors or the problem; the form then shows every value as it was sent (the kind
   with its roles, the checked boxes, the name, the tenant id) and moves focus to the errors.
3. `POST /sign-out` (`app/sign-out/route.ts`) expires the cookie on a 303 to the relative
   `/sign-in`, so the browser stays on whatever host it used. It refuses a request from another
   site with a 403 problem (`web-cross-origin-request`; the check is below), and any other
   method is a 405. The shells' account menu and the account page submit a plain form to it,
   so it works without JavaScript. Nothing is revoked at a provider today.
4. `/account` (`app/(app)/account/page.tsx`) shows the session's facts: display name, user id,
   tenant id and kind, roles, the second factor (asserted, verified or not), when the session
   started and expires (IST), and the provider, with the sign-out form.

## Cross-site requests

The cookie is `SameSite=Lax`, so a cross-site POST does not carry it. Next compares a server
action's `Origin` with the host before running it, and the sign-out handler runs the same kind
of check itself (`server/origin.ts`), as does the upload handler under `/api-bff/`:
`Sec-Fetch-Site` decides when the browser sends it (only
`same-origin` passes); otherwise `Origin`'s host must equal the request's `Host` header, or the
first `X-Forwarded-Host` value when `CW_WEB_TRUST_FORWARDED_IP` says the deployment trusts its
proxy's forwarded headers; a request with neither header is not a browser's cross-site
submission and passes. The check never uses `request.nextUrl`: under `next start` Next builds
that URL from the server's bind address (`http://localhost:PORT`), so comparing with it would
refuse every visitor who opened the app as `127.0.0.1`, a LAN address or a domain behind a
proxy, and a redirect built from it would send them to `localhost`. The proxy's redirects are
safe from this, because Next rewrites a proxy redirect to the request's own host into a
relative `Location`. `next` is a same-origin path or nothing. The session and the tokens never reach client
JavaScript: the cookie is httpOnly and the server passes only the `SessionDto`.

## Not enforced yet on `main`

- The fake provider verifies nothing: its second factor is asserted, and `/account` says so.
- A session ends only when it expires: identity's session version is not re-read until `/me`
  exists.
- `/account/mfa` is a waiting entry (it awaits identity's session routes); no page demands a
  second factor.
- `CW_WEB_ADMIN_IP_ALLOWLIST` and `CW_WEB_TRUST_FORWARDED_IP` are parsed and validated by
  `server/env.ts`, but the proxy does not check an allow-list yet; `/admin` is guarded by the
  session gates alone. `CW_WEB_TRUST_FORWARDED_IP` is read today only by the sign-out origin
  check, for `X-Forwarded-Host`.
- The services trust `x-tenant-id` from their caller (ADR-014 names that a dev-stage
  limitation); the web server sends the session's tenant, and no screen lets a user choose
  another.

## What the identity work changes

The code keeps room for these without renaming anything (ADR-014, ADR-019):

- `supabase` becomes an adapter behind the same port (phone OTP first, then an email link,
  server-side only); the fake adapter keeps its name and file and switches to identity's
  development provider tokens and the session exchange.
- The exchange's claims map onto `SessionClaims` (identity's `sub`, `tid`, `kind`, `sv`, `mfa`
  become `userId`, `tenantId`, `tenantKind`, `sv`, `mfa`), and the token fields fill in; the
  data layer sends `Authorization: Bearer` on every call.
- The proxy, never a render, refreshes a token about to expire, re-reads `/me` when
  `checkedAt` is old, and signs out a session whose `sv` is stale; it can write the new cookie
  on its response.
- A 403 `identity-mfa-required` sends the user to `/account/mfa`; the MFA roles need a
  verified second factor.
- The proxy checks the `/admin` allow-list from the request headers (a forwarded address only
  when `CW_WEB_TRUST_FORWARDED_IP` is set).
- Once every service verifies tokens, the flag `web.tenant_header_off` stops the
  `x-tenant-id` header.

## Tests

`session.test.ts` (round trip, tamper, expiry, wrong key, wrong shape, the cookie attributes per
environment), `dal.test.ts` (each gate's redirect or 404, the per-request cache; the cookie
store from `src/test/fake-cookies.ts`), `auth/fake.test.ts` and `auth/provider.test.ts`
(validation, the stable user id, the asserted second factor, the refusals), the sign-in form
and action tests, `proxy.test.ts` (the matcher through `next/experimental/testing/server` and
the decision for every registry page), and the Playwright specs `sign-in.spec.ts`,
`account.spec.ts` and `admin-gate.spec.ts` ([testing.md](testing.md)).
