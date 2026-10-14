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

| Claim                    | Meaning                                                               | Fake provider                                      |
| ------------------------ | --------------------------------------------------------------------- | -------------------------------------------------- |
| `userId`                 | the user                                                              | identity's user id for the persona                 |
| `tenantId`, `tenantKind` | the tenant the user acts in, and its kind                             | chosen on the form, or a new tenant identity makes |
| `roles`                  | one or more roles the kind allows                                     | chosen on the form; identity keeps them            |
| `displayName`            | shown in the header and on `/account`; the only personal data carried | chosen on the form                                 |
| `mfa`                    | whether a second factor was verified                                  | asserted `true` for MFA roles, not verified        |
| `sv`                     | identity's per-user session version; a bump revokes older sessions    | identity's, `0` at first                           |
| `provider`               | `fake` or `supabase`                                                  | `fake`                                             |
| `issuedAt`, `expiresAt`  | seconds since the epoch                                               | now, and now plus the lifetime                     |

The token claims the exchange fills: `cwToken` and `cwTokenExpiresAt` (identity's token for the
services), `providerRefreshToken` (what a refresh uses), `checkedAt` (when `/me` was last
re-read) and, kept across refreshes, `analyticsConsent`. [auth.md](auth.md) has the full
table and where each value comes from.

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
only in a server action or a route handler (the sign-in actions, the callback and the sign-out
handler), and by the proxy on its response (a refreshed or re-read session, a revoked one
cleared); a page or layout only reads. `sessionForRender()` gives shells and pages a
`SessionDto` (the facts, never a token field). Rotating the secret signs everyone out.

## The request path: proxy, then the gates

**`src/proxy.ts`** runs before a route renders (Next 16's proxy, Node runtime). Its matcher
skips `_next` assets, `/api/` and `/api-bff/` handlers and paths with a file extension (Next buffers
a request body for the proxy, which would cut an upload short; each `/api-bff/` handler runs the
shared handler gate first, below, D-059). For the rest, in order:

1. `decide(pathname, search, hasCookie, hasPending)` sends the visitor to
   `/sign-in?next=<path and query>` when the path is under `/admin` or matches a registry page
   whose roles are not `"public"`, and no `cw_session` cookie is present at all (a `cw_pending`
   cookie alone opens `/account/mfa`, where a pending sign-in verifies its factor). The roles
   are not checked here: a cookie that is present but expired, forged or short of the role is
   the gate's business, and public pages, route handlers and unknown paths pass.
2. Under `/admin`, the allow-list (`adminGate`): the client address from `x-real-ip`, else the
   first `x-forwarded-for` hop, both only when `CW_WEB_TRUST_FORWARDED_IP` says the proxy in
   front sets them, else none (D-070); `CW_WEB_ADMIN_IP_ALLOWLIST` as IPv4 and IPv6 ranges
   (`shared/lib/cidr.ts`). An empty list opens `/admin` to every address in local, test and
   staging (one warning at start, `src/instrumentation.ts`) and to none in prod, where the
   tools answer 404 as if they did not exist; an address outside the list is rewritten to
   `/forbidden`.
3. Session upkeep: the cookie is decrypted, the identity token refreshed when it is about to
   expire, `/me` re-read when the last read is old, and a session identity revoked is cleared
   on a redirect to `/sign-in?reason=signed-out`; the new cookie goes on the response and into
   the request the render sees ([auth.md](auth.md), "Refresh, re-read and revocation"). These
   are the only requests on which the proxy calls a service.
4. A `Content-Security-Policy` with a nonce for this request's scripts, forwarded as `x-nonce`
   so Next applies it to its own; the other security headers stay in `next.config.ts`.

The proxy is not on a server action's path.

**`server/dal.ts`** is the authoritative gate. Each function reads the cookie through
`verifySession()`, which decrypts once per request (React `cache`).

| Gate                            | Answers                                                                                                        |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `verifySession()`               | the claims, or `null`                                                                                          |
| `requireSession({ next })`      | the claims, or a redirect to `/sign-in?next=`                                                                  |
| `requireRole(roles, { next })`  | the claims when a role matches; anonymous to sign-in, wrong role to `/forbidden`; `"public"`: optional session |
| `requireTenantKind(kinds)`      | the claims when the tenant kind matches, else `/forbidden`                                                     |
| `requireAdmin({ next })`        | a regulatory role, else `notFound()`: a tenant role must not learn that a tool exists                          |
| `requireMfa({ next })`          | a session whose roles need a second factor has one, else a redirect to `/account/mfa?next=`                    |
| `requireScreen(screen, params)` | an entry's roles and tenant kinds; an admin entry through `requireAdmin`, 404 for a role it does not list      |
| `requireScreenSession(screen)`  | `requireScreen` for an entry that is never public                                                              |
| `sessionForRender()`            | the render-safe view, or `null`; for shells, never a decision                                                  |

Where they run: every `page.tsx` calls its gate on the first line (`/account` uses
`requireScreenSession`); the two catch-alls call `requireScreen` with the matched entry, so a
waiting screen is gated exactly like the live one it will become; the admin layout calls
`requireAdmin` then `requireMfa` (the outer wall: a tenant role gets the 404 before any admin
markup exists, and a regulatory role without its second factor verifies it first) and every
admin page calls `requireAdmin` again, because a layout does not re-run on every navigation; the
two team pages call `requireMfa` too; every server action calls its gate again. The gates never
write a cookie.

**The handlers under `/api-bff/`** (a stored file's bytes, an upload) are reached by no proxy, so
each route file's exported method starts with `gateHandler(entry, request)` from
`server/bff/gate.ts`, given its own registry entry: for a method that writes, the origin check
(below) before anything else; without a session, a GET goes to `/sign-in?next=` and comes back
and any other method is a 401 problem; a tenant role gets a 404 for a regulatory tool, and a role
short of the entry a 403 that names the entry's roles. `src/test/handler-gate.test.ts` fails,
naming the file, for a handler that does anything before it. The proxy's upkeep (the token
refresh, the `/me` re-read, the stale-session sign-out) does not run for these handlers: a
handler's call with a token identity no longer knows is answered 401 by the service and ends
the request on the sign-in page like a page's would (D-059).

**Where a visitor lands.** `signInHref(next)` builds `/sign-in?next=` only for a same-origin
path worth returning to (not `/`, not the sign-in page itself). `safeNext(next, fallback)`
accepts only a path that starts with a single `/` and has no backslash, control character,
whitespace or scheme, so `next` cannot redirect off the site. After sign-in the visitor goes to
that path or to `homeFor(session)`: `/admin` for the regulatory roles, `/businesses` for every
tenant role. `forbiddenHref()` is `/forbidden`, a public page with a way out.

## Sign-in

**The port.** `server/auth/provider.ts` declares `AuthProvider`: `name`, the `methods` it
offers (`dev`, `phone`, `email`), the phone code (`startPhoneOtp`, `verifyPhoneOtp`), the email
link (`sendEmailLink`, `exchangeEmailLink`), `refresh`, `signOut`, the `mfa` port and, for the
fake alone, `signInAsPersona`. Every method answers a `Result`; a refusal is a web-local
problem (`web-provider-<kind>`: invalid code, expired, rate limited, unavailable, invalid link,
invalid contact, unsupported), which a form shows like a service's. `providerFor(env)` picks the
adapter named by `CW_WEB_AUTH_PROVIDER`:

| Value      | Adapter                                                                                                      |
| ---------- | ------------------------------------------------------------------------------------------------------------ |
| `fake`     | `server/auth/fake.ts`: identity's development provider tokens; local and test only                           |
| `supabase` | `server/auth/supabase.ts`: Supabase Auth over GoTrue's REST API, with `CW_WEB_SUPABASE_URL` and the anon key |
| unset      | "Sign-in is not configured", naming the variable                                                             |

The pages, the actions, the proxy and the session module never name an adapter.

**The exchange.** Whatever the adapter answers is a provider session (its access and refresh
tokens, the assurance level, the subject), which `server/auth/sessions.ts` exchanges at
`POST /v1/identity/sessions` for identity's own token and the facts the cookie carries. The
flows (sign-in, sign-up, the email link, the second factor, refresh and revocation) are drawn
in [auth.md](auth.md); in short: a person identity does not know yet signs up (`/sign-up`), a
role that needs a second factor verifies it first (`/account/mfa`), and the verified provider
session waits in `cw_pending` between those steps, never in a URL (D-068).

**The fake adapter.** The development sign-in keeps its form (`features/auth/ui/dev-sign-in-form.tsx`):
a tenant kind, one or more roles the kind allows (the checkboxes follow the kind), a display
name (at most 80 characters) and an optional tenant id (a UUID; empty makes a new tenant).
"Use the last seeded tenant" fills the tenant id from `var/seed/last.json` when `make web-seed`
has written it. `validateFakeSignIn` names each field that fails; then identity makes the
persona (`POST /v1/identity/dev/provider-tokens` with the kind, the roles and the name: the
tenant with that id or a new one, the user with those roles, the one development internal
tenant for the regulatory roles) and signs a provider token at aal2 for the roles that need a
second factor, which the same exchange turns into a session. The persona's address is a version
5 UUID of the tenant and the lower-cased display name at `fake.compliancewatch.invalid`, so
the same name in the same tenant is the same user across sign-ins (and `decided_by` stays
stable). The phone and email methods work on the fake too: any six digits pass, and the email
link is shown on the next page instead of sent. It is refused twice outside `local` and
`test`: the environment schema rejects `CW_WEB_AUTH_PROVIDER=fake` there, the adapter's
constructor refuses again (D-016), and identity serves the development route only with its own
fake provider in local and test.

**The pages and handlers.**

1. `/sign-in` (`app/(public)/sign-in/page.tsx`): a visitor who already has a session goes on to
   `next` or the role home; otherwise the page asks `providerFor` and renders the method the
   `method` query names among those the provider offers (the development form first on the
   fake), with links to the others, the notice a `reason` or `error` query carries (a session
   that ended, an expired link, a registered person), or the "not configured" state.
2. The actions (`features/auth/actions.ts`): `signIn` (the persona), `startPhoneSignIn`,
   `verifyPhoneCode`, `sendEmailLink`, `signUp`; and `features/auth/mfa-actions.ts`:
   `verifySecondFactor`, `enrolAuthenticator`, `removeAuthenticator`. Each shape-checks its form
   (`features/auth/model/sign-in.ts`), asks the provider, hands the result to the flow and ends
   as `finishSignIn` says (`features/auth/flow.ts`): the cookie and a redirect to
   `safeNext(next, homeFor(session))` (a new tenant's owner lands on onboarding), the sign-up
   or second-factor step with `cw_pending`, or the state the form shows (field errors, the
   problem, a refusal in words). The forms keep what was typed and move focus to the errors.
3. `GET /auth/callback` (`app/auth/callback/route.ts`): the email link's `token_hash`, exchanged
   with the provider and then with identity; an invalid or expired one returns to
   `/sign-in?error=link-expired`.
4. `POST /sign-out` (`app/sign-out/route.ts`) revokes the provider session where one is kept
   (Supabase), expires the session, pending and remembered-recipients cookies on a 303 to the
   relative `/sign-in`, so the browser stays on whatever host it used, and refuses a request
   from another site with a 403 problem (`web-cross-origin-request`; the check is below); any
   other method is a 405. The shells' account menu and the account page submit a plain form to
   it, so it works without JavaScript.
5. `/account` (`app/(app)/account/page.tsx`) shows the session's facts (display name, user id,
   tenant id and kind, roles, the second factor as asserted, verified or not, when the session
   started and expires in IST, the provider) and what `GET /v1/identity/me` adds (email, mobile
   number, the account's name), with the way to `/account/mfa` and the sign-out form. When
   identity reads no token (header mode) or does not answer, the page says so and shows the
   session's facts alone.
6. `/account/mfa` (`app/(app)/account/mfa/page.tsx`): two-step verification for a signed-in
   person or a pending sign-in: one confirm on the fake; enrol (QR code and secret), challenge
   and removal of an authenticator app on Supabase.
7. `/settings/team` and `/admin/team` (`features/team`): the tenant's people on identity's user
   routes with the session's bearer: invite (one contact, a name, the roles the kind allows),
   change roles, disable with a reason; identity's refusals (the last admin, a role the kind
   lacks, the plan's seat limit with the way to billing) show in the dialogs, and nobody can
   disable themselves.

## Cross-site requests

The cookie is `SameSite=Lax`, so a cross-site POST does not carry it. Next compares a server
action's `Origin` with the host before running it, and the sign-out handler runs the same kind
of check itself (`server/origin.ts`), as does the handler gate for a write under `/api-bff/` (the
upload handler's): `Sec-Fetch-Site` decides when the browser sends it (only `same-origin`
passes); otherwise `Origin`'s host must equal the request's `Host` header, or the
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
- Revocation outside identity is bounded by the identity token's life (10 minutes) plus the
  proxy's re-read interval (`CW_WEB_SESSION_RECHECK_SECONDS`, 5 minutes): a disabled user keeps
  reading the other services until the sooner of the two.
- The services take the tenant from `x-tenant-id` in header mode (the local product) and from
  the token in dual and token mode; the web sends both, equal, until every service runs token
  mode and `web.tenant_header_off` stops the header (W13). An admin lookup of another tenant
  goes without the bearer until then (D-069).
- The clients built without a session (the rulebook, the pipeline, the engine's admin routes)
  keep their shared tokens and send no bearer.
- The Supabase adapter has met recorded responses only; its first live run is in the release
  checklist.

## Tests

`session.test.ts` (round trip, tamper, expiry, wrong key, wrong shape, the cookie attributes per
environment), `pending.test.ts`, `dal.test.ts` (each gate's redirect or 404, the second-factor
gate, the per-request cache; the cookie store from `src/test/fake-cookies.ts`),
`auth/fake.test.ts`, `auth/supabase.test.ts` (every GoTrue call against the recorded shapes in
`src/test/gotrue-fixtures.ts`, the error mapping) and `auth/provider.test.ts`,
`auth/sessions.test.ts` and `auth/usecases.test.ts` (the exchange's branches, sign-up, the
re-read, refresh and revocation, over the identity stand-in in `src/test/identity-fixture.ts`),
`shared/lib/cidr.test.ts`, `shared/config/roles-parity.test.ts`, the sign-in, sign-up, MFA and
team forms and their action tests, the callback and sign-out handler tests, `proxy.test.ts`
(the matcher through `next/experimental/testing/server`, the decision for every registry page,
the allow-list, the policy and the cleared cookie), and the Playwright specs `sign-in.spec.ts`,
`sign-up.spec.ts`, `mfa.spec.ts`, `team.spec.ts`, `admin-allowlist.spec.ts`,
`revocation.spec.ts`, `account.spec.ts` and `admin-gate.spec.ts` ([testing.md](testing.md)).
