# ADR-019: The web app reaches the services only through its server layer, with an encrypted stateless session

- **Status:** Proposed
- **Date:** 2026-09-29
- **Deciders:** Core Product (owner of `apps/web`), Identity and Partner, Platform and Infrastructure

## Context

`apps/web` renders the owner, CA-firm and internal screens over ten services (ADR-002). What
those services expect of a caller today:

- No service sends CORS headers, and none is meant to be called from a browser.
- The tenant is named by the `x-tenant-id` header until identity issues verified tokens
  (ADR-014 calls the header a dev-stage limitation that ends there).
- The rulebook's write routes need a shared secret in `x-cw-write-token`, and its analyst
  routes a second one in `x-cw-review-token` (ADR-018). A secret that reaches a browser is no
  longer a secret.
- Every error is an RFC 9457 problem carrying the caller's `x-request-id` as its
  `correlation_id`, which is how support finds the log line.

The app also needs to know who is asking on every request: which tenant, which roles, whether
a second factor was verified. The identity routes that will answer that (the session exchange,
`/me`) are not on `main`, and the managed deployment profile (ADR-013) puts the app on a host
where a session store would be one more managed service to run.

## Decision

1. **The browser never calls a service.** Every service call is made by the Next.js server: a
   server component while it renders, a server action, or a route handler. The calls go through
   one server-only layer, `apps/web/src/server`, whose every file starts with
   `import "server-only"`, so a client bundle cannot import it. The app has no `NEXT_PUBLIC_*`
   variable: no service URL and no token is compiled into anything the browser loads. Client
   components receive plain props.
2. **One typed client per service, one header contract.** The clients are `openapi-fetch`
   bound to the TypeScript types generated from the committed OpenAPI specs (`make openapi-ts`;
   `make openapi-ts-check` fails on drift). Each call sends an `x-request-id`; the
   tenant-scoped services get `x-tenant-id` from the session (or from an explicit override that
   only admin lookups use); the rulebook, which holds records shared by every tenant, gets no
   tenant header; a shared secret is attached only by the factory for that purpose, after it
   has checked that the session holds a regulatory role. Answers become `Result` values: the
   data, or an error whose kind follows the status, with the problem and the request id.
   Expected failures are values, never exceptions.
3. **The session is an encrypted cookie, not a server-side record.** `cw_session` is a JWE
   (`dir` key management, A256GCM) under a 32-byte secret only the server holds, httpOnly,
   SameSite=Lax, Secure outside local development, eight hours by default. It carries the
   claims the gates read (user, tenant, tenant kind, roles, display name, second factor, the
   identity session version, the provider, issue and expiry) and has room for the identity
   token fields. The browser holds ciphertext it can neither read nor forge. The cookie is
   written only by server actions and route handlers; the proxy (`src/proxy.ts`) checks that
   it is present; the data access layer (`server/dal.ts`) decrypts it once per request and is
   the authoritative gate for every page, action and handler.
4. **Sign-in goes through a provider port.** The pages and actions ask an `AuthProvider` for
   the claims and never name an adapter. The only adapter on `main` is a development fake that
   exists where the app's environment is `local` or `test` and is refused elsewhere; the
   identity provider of ADR-014 is added as a second adapter behind the same port.
5. **The header contract ends with verified tokens.** When identity issues tokens, the session
   carries the token, the server layer sends it as `Authorization: Bearer` on every call, the
   proxy (never a render) refreshes it and re-reads the session version, and the tenant header
   stops once every service verifies the token instead.

## Alternatives considered

The browser calls the services directly, with CORS on each service and a bearer token held in
JavaScript. It removes one hop, but it exposes the token to any script injection, needs a CORS
policy on ten services, cannot use the rulebook's shared secrets at all, and turns the tenant
header into a value the browser chooses.

A separate backend-for-frontend service. The Next.js server already runs on every request and
renders on the server; a second deployable in front of the services would duplicate it.

A server-side session table (an opaque cookie keyed into Redis or Postgres). Revocation would
be immediate, but every request would need a store lookup, and the managed profile would need a
store for the app alone. Identity's per-user session version gives revocation once `/me`
exists, without a table.

An authentication library (Auth.js and similar). It brings its own provider and session models
and adapters, while the identity exchange still has to be written; what the app needs is an
encrypted cookie (`jose`) and a port.

A generated HTTP client package. The contracts package stays types and schemas; the request
layer (headers, timeouts, problem mapping, caching) belongs to the app that makes the calls.

## Consequences

- Every read and write takes one more hop, browser to Next.js server to service. The server
  renders the page anyway, so a read costs nothing extra for the browser; the service ports
  need not be reachable from the internet at all.
- The Next.js server holds the secrets: `CW_WEB_SESSION_SECRET` and the rulebook's write token
  today, the review token when the analyst screens arrive. They are set per environment on the
  hosting project and rotated with the other secrets; rotating the session secret signs every
  user out.
- Until identity exists a session is revoked only by expiry; the session version is re-read in
  the proxy once `/me` is on `main`, because a cookie may be rewritten there but never during a
  render (Next 16 allows `cookies().set` only in server actions and route handlers).
- Until the services verify tokens, any caller that can reach a service can still send any
  `x-tenant-id`. This decision adds nothing to that exposure; ADR-014's verified claims remove
  it.
- A feature that needs data in the browser after the page loads (polling, streaming) goes
  through a route handler of the app, never a direct call. A partner or mobile client uses the
  public `/v1` API, not this layer.
- The cookie stays small (a few hundred bytes today, about a kilobyte more with the identity
  token), under the browser's four-kilobyte limit.
- Revisit when a screen needs real-time data the server cannot relay cheaply, when identity
  sessions land (the adapter and the proxy change, the pages do not), or if the app moves to a
  host where a server-side session store is free to run.
