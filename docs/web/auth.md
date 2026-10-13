# Sign-in through the identity service

How a person gets a session, how it stays current and how it ends, as built in W3. The roles,
the gates and the cookie's place in a request are in [auth-and-roles.md](auth-and-roles.md);
this file is the flows, the cookies' contents, the mapping of identity's token onto the
session, the two provider adapters, the threats considered, and the local set-up.

## The parts

| Part                            | Where                                                                                                                         | Does                                                                                                                                                                                                                                                                                                                                                                                                |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The provider port               | `server/auth/provider.ts`                                                                                                     | `AuthProvider`: a phone code (`startPhoneOtp`, `verifyPhoneOtp`), an email link (`sendEmailLink`, `exchangeEmailLink`), `refresh`, `signOut`, the `mfa` port (`listFactors`, `enrolTotp`, `challenge`, `verify`, `remove`), and the development persona (`signInAsPersona`, fake only). Every method answers a `Result`; a refusal is a web-local problem `web-provider-<kind>` (`providerFailure`) |
| The fake adapter                | `server/auth/fake.ts`                                                                                                         | identity's development provider tokens (`POST /v1/identity/dev/provider-tokens`); local and test only                                                                                                                                                                                                                                                                                               |
| The Supabase adapter            | `server/auth/supabase.ts`                                                                                                     | GoTrue's REST API over fetch, server-side, with the anon key; no supabase-js (D-067)                                                                                                                                                                                                                                                                                                                |
| The exchange                    | `server/auth/sessions.ts`                                                                                                     | `POST /v1/identity/sessions` and `POST /v1/identity/tenants` mapped to the flow's steps; `GET /v1/identity/me` for the re-read and the account page                                                                                                                                                                                                                                                 |
| The flows                       | `server/auth/usecases.ts`                                                                                                     | `signInWithProviderSession`, `completeSignUp`, `completeMfa`, `refreshSession`, `keepSessionCurrent`: nothing of Next in them                                                                                                                                                                                                                                                                       |
| The pending cookie              | `server/auth/pending.ts`                                                                                                      | `cw_pending`: the verified provider session between the steps (D-068)                                                                                                                                                                                                                                                                                                                               |
| The actions, handlers and pages | `features/auth`, `app/(public)/sign-in`, `app/(public)/sign-up`, `app/auth/callback`, `app/sign-out`, `app/(app)/account/mfa` | the forms, the callback, sign-out, two-step verification                                                                                                                                                                                                                                                                                                                                            |
| The proxy                       | `src/proxy.ts`                                                                                                                | session upkeep (refresh, re-read, the sign-out of a revoked session), the `/admin` allow-list, the CSP nonce                                                                                                                                                                                                                                                                                        |
| The bearer                      | `server/api/services.ts`                                                                                                      | `Authorization: Bearer <identity token>` on every call made for a session (D-069)                                                                                                                                                                                                                                                                                                                   |

## The flows

Identity's answers the web maps (`server/auth/sessions.ts`): 404 `identity-user-not-provisioned`
is sign-up; 403 `identity-mfa-required` is the second factor; 403 `identity-user-disabled` and
403 `identity-tenant-deleting` are refusals the form words; 409 `identity-subject-registered` on
a sign-up returns the person to sign in; 503 `identity-provider-unavailable` and a connection
that fails are "the sign-in provider is not available"; anything else is shown as the problem
it is.

### Sign in by phone, then sign up

```mermaid
sequenceDiagram
    participant B as Browser
    participant W as Web server
    participant P as Provider (GoTrue or the fake)
    participant I as Identity
    B->>W: POST startPhoneSignIn {phone}
    W->>P: send a code to the phone
    W-->>B: the code step
    B->>W: POST verifyPhoneCode {phone, code}
    W->>P: verify the code
    P-->>W: provider session (access, refresh, aal1)
    W->>I: POST /v1/identity/sessions {provider_token}
    alt the person is a user
        I-->>W: 200 session (token, tenant, kind, user, name, roles, mfa, sv)
        W-->>B: Set-Cookie cw_session; 303 next or the role's home
    else nobody yet
        I-->>W: 404 identity-user-not-provisioned
        W-->>B: Set-Cookie cw_pending (5 min); 303 /sign-up
        B->>W: POST signUp {kind, name, your name}
        W->>I: POST /v1/identity/tenants {kind, name, provider_token, display_name}
        I-->>W: 201 tenant, user, session
        W-->>B: Set-Cookie cw_session, cw_pending cleared; 303 /onboarding
    end
```

The phone step normalises what was typed (`normaliseSignInPhone`: spaces and dashes dropped, a
ten-digit Indian number given `+91`) and refuses anything that is not E.164. The code step
offers another code after 30 seconds (`RESEND_AFTER_SECONDS`) and a way back to the number. A
business is created at once; a CA firm's first user is a CA admin, who needs the second factor,
so that sign-up ends on the MFA step below with the form kept in `cw_pending`.

### The email link

```mermaid
sequenceDiagram
    participant B as Browser
    participant W as Web server
    participant P as Provider
    participant I as Identity
    B->>W: POST sendEmailLink {email}
    W->>P: send a link to /auth/callback?next= (the fake hands it back instead)
    W-->>B: 303 /sign-in/email-sent
    B->>W: GET /auth/callback?token_hash=&type=magiclink&next=
    W->>P: exchange the hash
    P-->>W: provider session
    W->>I: POST /v1/identity/sessions
    I-->>W: as above
    W-->>B: Set-Cookie; 303 next, /sign-up or /account/mfa
```

The callback is a route handler (`app/auth/callback/route.ts`): the hash is single-use at the
provider and never lands in a page of this app; an invalid or expired one returns to
`/sign-in?error=link-expired`. With the fake adapter in local and test nothing is sent: the
email-sent page shows the link, read from `cw_pending`.

### The second factor

```mermaid
sequenceDiagram
    participant B as Browser
    participant W as Web server
    participant P as Provider
    participant I as Identity
    B->>W: GET /account/mfa (a session, or cw_pending)
    W-->>B: confirm (fake) or enrol/challenge an authenticator app (Supabase)
    B->>W: POST verifySecondFactor {code?}
    W->>P: challenge, then verify
    P-->>W: provider session at aal2
    W->>I: POST /v1/identity/sessions (or /tenants for the kept sign-up)
    I-->>W: 200 session with mfa true
    W-->>B: Set-Cookie cw_session; 303 next, or /account
```

`requireMfa()` (`server/dal.ts`) sends a session whose roles need the factor
(`MFA_REQUIRED_ROLES`: analyst, reviewer, admin, ca_admin) and lacks it to `/account/mfa?next=`;
the admin layout and the two team pages call it. A person whose roles need none may enrol all
the same. The proxy lets `cw_pending` alone through to `/account/mfa`, since a pending sign-in
has no session yet. With Supabase, removing a factor needs a fresh code; with the fake, the
page has nothing to enrol or remove.

### Refresh, re-read and revocation

```mermaid
sequenceDiagram
    participant B as Browser
    participant X as Proxy
    participant P as Provider
    participant I as Identity
    B->>X: any page request with cw_session
    alt the identity token has under 120 s left
        X->>P: refresh (the cookie's refresh token)
        P-->>X: provider session
        X->>I: POST /v1/identity/sessions
        I-->>X: a fresh token (or a refusal: revoked)
    end
    alt /me was last read over 300 s ago
        X->>I: GET /v1/identity/me (bearer)
        I-->>X: roles, mfa, session version, name (or 401 identity-session-revoked)
    end
    X-->>B: the page, with Set-Cookie when anything changed; or Set-Cookie cw_session= and 303 /sign-in?reason=signed-out
```

`keepSessionCurrent` (`server/auth/usecases.ts`) runs in the proxy, never in a render (a render
cannot write a cookie). The margins are `CW_WEB_TOKEN_REFRESH_SECONDS` (120) and
`CW_WEB_SESSION_RECHECK_SECONDS` (300; 0 re-reads on every request, which the e2e run sets to 2
seconds). A refresh keeps the session's own window: a cookie still ends eight hours after
sign-in. An identity that does not answer, or that reads no token (header mode), defers: the
claims stand and `checkedAt` is bumped so the next request does not ask again at once.

A render that meets a 401 `auth-token-invalid` from any service, or `identity-session-revoked`
from identity, on a call that carried the bearer ends on `/sign-in?reason=signed-out`
(`call()` in `server/api/client.ts`, `server/auth/signed-out.ts`); the proxy clears the cookie
on the way there (D-071). Revocation is therefore bounded: a bumped session version or a
disabled user takes effect at identity at once, at the other services when the identity token
expires (10 minutes), and in the browser at the next proxy re-read (5 minutes) at the latest.

### Sign-out

`POST /sign-out` revokes the provider session where one is kept (Supabase: the refresh token's
session at GoTrue; the fake keeps none), expires `cw_session`, `cw_pending` and the remembered
recipients cookie, and answers a relative 303 to `/sign-in`. It refuses another site's POST.

## The cookies

**`cw_session`** (`server/session.ts`): a JWE under `CW_WEB_SESSION_SECRET` (dir, A256GCM),
httpOnly, SameSite=Lax, Secure outside local, path `/`, eight hours
(`CW_WEB_SESSION_TTL_SECONDS`).

| Claim                         | From identity's answer                         | Notes                                                                                    |
| ----------------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `userId`                      | `user_id` (the token's `sub`)                  |                                                                                          |
| `tenantId`, `tenantKind`      | `tenant_id` (the token's `tid`), `tenant_kind` | the kind decides which screens and roles apply                                           |
| `roles`                       | `roles`                                        | brought up to date by the re-read                                                        |
| `displayName`                 | `display_name`                                 | "User <first eight of the id>" when the person gave none                                 |
| `mfa`                         | `mfa`                                          | the fake asserts it (the account page says so); Supabase verifies it                     |
| `sv`                          | `session_version`                              | identity's per-user version; a bump revokes older sessions                               |
| `provider`                    | the adapter                                    | `fake` or `supabase`                                                                     |
| `issuedAt`, `expiresAt`       | now, now plus the lifetime                     | a refresh never extends them                                                             |
| `cwToken`, `cwTokenExpiresAt` | `access_token`, now plus `expires_in`          | the bearer for the services (ES256 JWT with `sub`, `kind`, `tid`, `roles`, `sv`, `mfa`)  |
| `providerRefreshToken`        | the provider session's refresh token           | what a refresh and a provider sign-out use; the fake's encodes the contact and the level |
| `checkedAt`                   | now                                            | when `/me` was last read                                                                 |
| `analyticsConsent`            | kept across refreshes                          | the analytics consent the onboarding recorded                                            |

No email, phone or tenant name travels in the cookie: the account page reads them from `/me`
on each visit.

**`cw_pending`** (`server/auth/pending.ts`): the same JWE, five minutes, carrying the provider
name, the verified provider session, the contact (phone or email), `next`, and the sign-up form
when a CA firm's first admin still has to verify the factor. A provider token never travels in
a URL (D-068).

## The providers

| Step             | Fake (`CW_WEB_AUTH_PROVIDER=fake`, local and test)                                                                                           | Supabase (`supabase`, with `CW_WEB_SUPABASE_URL` and `CW_WEB_SUPABASE_ANON_KEY`)                                              |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Phone code       | nothing is sent; any six digits pass; `POST /dev/provider-tokens {phone}` signs the token                                                    | `POST /auth/v1/otp {phone}`, then `POST /auth/v1/verify {type sms, phone, token}`                                             |
| Email link       | the link is shown on the email-sent page instead of sent                                                                                     | `POST /auth/v1/otp {email, create_user}` with `redirect_to`, then `POST /auth/v1/verify {type magiclink, token_hash}`         |
| Refresh          | the contact and the level are in the refresh token; a new token is signed                                                                    | `POST /auth/v1/token?grant_type=refresh_token`                                                                                |
| Sign-out         | nothing                                                                                                                                      | `POST /auth/v1/logout?scope=local` with a fresh access token                                                                  |
| Second factor    | one confirm button; the token is signed at aal2 (`mfaMode: "confirm"`)                                                                       | TOTP: `GET/POST /auth/v1/factors`, `/factors/{id}/challenge`, `/factors/{id}/verify`, `DELETE /factors/{id}` (`"totp"`)       |
| Development form | a persona (tenant kind, roles, name, optional tenant id) made by identity on the spot; its address is `<uuid5>@fake.compliancewatch.invalid` | none                                                                                                                          |
| Refusals         | identity's own problems pass through (a persona the kind lacks, the last admin)                                                              | 429 rate limited (Retry-After), `otp_expired` expired, 400/422 invalid code, 401/403 expired or invalid link, 5xx unavailable |

The Supabase adapter is checked against recorded response shapes only
(`src/test/gotrue-fixtures.ts`) until the project exists; the first live run is in the release
checklist. The adapter reads the session's level from the access token's `aal` claim and never
verifies the token: identity does, against the project's keys (`services/identity`).

## The bearer and the tenant header

Every call a gateway makes for a session carries `Authorization: Bearer <cwToken>` with
`x-tenant-id` equal to the token's tenant, and `x-request-id`. The services read the token in
`dual` and `token` mode and ignore it in `header` mode (the local product); `make web-stack
AUTH=dual` and the `web-e2e` CI job run the stack in dual mode, which identity's `/me` and user
routes need. An admin lookup of another tenant (`ctx.tenantId`) goes without the bearer, since
a token naming one tenant with a header naming another is a 403 `auth-tenant-mismatch`; the
clients built without a session (the rulebook, the pipeline, the engine's admin routes) keep
their shared tokens and send no bearer. `decided_by`, `recorded_by` and `changed_by` fields
come from the session's user id, as before; identity ignores them in token mode. The header
goes when every service runs token mode (W13; the flag `web.tenant_header_off` is reserved for
it).

## Threats considered

- **A stolen cookie** is a stolen session until it expires: eight hours at most, and less once
  identity revokes it (a change of roles, a disabled user: the next proxy re-read ends it, five
  minutes at most). The cookie is httpOnly, so a script cannot read it, and encrypted, so its
  holder learns nothing from it. Signing out revokes the provider session where one is kept.
- **A provider token in a URL** would sit in logs and history: the email link's hash is the
  provider's single-use token and lands only in the callback handler; everything else travels
  in `cw_pending`.
- **A forged `next`** cannot leave the site: `safeNext` accepts only a same-origin path.
- **A forged client address**: the allow-list reads `x-real-ip` and `x-forwarded-for` only when
  `CW_WEB_TRUST_FORWARDED_IP` says the deployment's proxy sets them (Vercel does); elsewhere the
  address is unknown and a non-empty list admits nobody (D-070).
- **A forced sign-out**: `/sign-in?reason=signed-out` clears the cookie without a check, so a
  cross-site link can sign a person out; it cannot sign anyone in or read anything (D-071).
- **The fake adapter in production**: refused by the environment schema and by its constructor,
  and identity serves the development route only with its own fake provider in local and test.
- **An unverified second factor**: the fake asserts it and the account page says so; nothing
  about the fake leaves local and test.

## Local set-up

```sh
make web-stack AUTH=dual && make web-stack-wait && make web-seed   # identity in memory, the fake provider
make web-dev                                                        # CW_WEB_AUTH_PROVIDER=fake in apps/web/.env.local
```

`/sign-in` offers the development sign-in (a persona), a phone code (any six digits) and an
email link (shown on the next page). The user's own stack keeps header mode; sign-in works
there too, with the account page saying that identity reads no token and the re-read deferred.
Supabase needs `CW_WEB_AUTH_PROVIDER=supabase`, the project's URL and anon key on the web app,
and identity's own `CW_AUTH_PROVIDER=supabase` with the service-role key
(`services/identity/README.md`, "Supabase: manual steps").
