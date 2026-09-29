# ADR-014: Supabase Auth as the identity provider of the MVP profile; Keycloak stays the option for the Kubernetes profile

- **Status:** Proposed
- **Date:** 2026-09-28
- **Deciders:** Identity and Partner, Platform and Infrastructure, with the maintainer as product owner (decision taken 2026-09-28)

## Context

ADR-009 records Keycloak, self-hosted, for identity: OIDC and SAML, data in region, no
per-user cost. The guide lists the alternative as an open question for the moment SSO customers
appear (section 21). ADR-013 moves the MVP to a managed profile with no cluster, which makes a
self-hosted identity server the largest piece of infrastructure the MVP would run, for one of
the smallest parts of the product.

The MVP's users are owners of small businesses who live on WhatsApp, and staff of CA firms
who live in email. The first login must be a phone number and a one-time code, with email as
the second path; enterprise SSO is a later need. Personal data (name, phone, email) must stay
in India (DPDP, guide section 16), and the identity provider must give every service a token
with a tenant id and roles that the API layer verifies and the database's row-level security
reads.

Three candidates were compared:

| | Supabase Auth | Keycloak (self-hosted) | Clerk |
| --- | --- | --- | --- |
| Phone OTP | yes, through an SMS provider | not built in; extension work | yes |
| Hosting | managed; a project can be placed in the Mumbai region | ours: a server, a database, upgrades, backups | managed; regions and residency to be confirmed per plan |
| Cost | free tier, then per monthly active user | none per user; operations time | per monthly active user, higher |
| Enterprise SSO | on a paid plan | yes, SAML and OIDC | yes, on a paid plan |
| Fit with the MVP profile | same vendor family as a managed Postgres option; JWT with JWKS | needs the Kubernetes profile to be worth running | good, but the most vendor-shaped |

## Decision

The MVP profile uses Supabase Auth. Sign-in is phone number with OTP (an Indian SMS provider
configured in the Supabase project) and email with a magic link or password; enterprise SSO
waits for the Kubernetes profile or a plan that offers it. Supabase issues the JWT; the API
layer verifies it against the project's JWKS; the identity service maps the token's subject to
a user, the user to a tenant and roles, and puts `tenant_id` and `roles` into the claims the
services and row-level security read. Every service keeps trusting only that verified claim
set, never a header, once identity exists (the gateway's `x-tenant-id` header is a dev-stage
limitation that ends here).

Keycloak stays the option of the Kubernetes profile (ADR-009 keeps its status). Both are OIDC:
the identity service depends on an `IdentityProvider` protocol (verify a token, look up a
subject, provision a user) with a Supabase implementation and a fake for tests; a Keycloak
implementation slots in later and users migrate by an export of subjects and phone numbers.

Nothing is created by this decision. The Supabase project, its region, the SMS provider and the
keys are manual steps for the maintainer, listed in the identity work package; until then the
identity service runs with the fake provider behind `CW_AUTH_PROVIDER=fake`.

## Consequences

- No identity server to run in the MVP; sign-in works from day one for the users the product
  actually has.
- Per-user cost appears above the free tier; the pricing work package models it against the
  per-business price.
- The project must be created in the Mumbai region and the SMS provider must keep phone
  numbers in India; both are checklist items with the DPDP data map, not assumptions.
- Supabase's JWT shape and JWKS rotation are a dependency; the verifier is one class with
  tests against recorded tokens, so a change there is contained.
- SAML for enterprise tenants is not available on the MVP profile; that is an accepted gap
  until the Kubernetes profile.
- Revisit when an SSO customer signs, when monthly active users make the per-user cost
  larger than running Keycloak, or when the Kubernetes profile goes live.

## Addendum 2026-09-29: token exchange, revocation, second factor and key rotation

The identity service now signs people in through an `IdentityProvider` (the fake one locally, a
Supabase adapter behind `CW_AUTH_PROVIDER=supabase`) and issues the tokens every service
verifies. How it does so:

- **Services see identity's token, never the provider's.** The web exchanges the provider's token
  at `POST /v1/identity/sessions` for identity's access token: an ES256 JWT with the claims `iss`,
  `aud`, `sub`, `kind` (user or service), `tid` (the tenant), `roles`, `scp` (scopes), `sv` (the
  session version), `mfa`, `iat`, `exp` and `jti`, and `kid` in its header. Services verify it
  against identity's key set at `/v1/identity/.well-known/jwks.json` and read the tenant and roles
  from it. They trust one issuer and one claim shape, so replacing Supabase with Keycloak
  (ADR-009) changes identity's provider adapter and nothing else. Service clients get the same
  kind of token for their id and secret at `POST /v1/identity/service-tokens`, with scopes and no
  roles.
- **Revocation is immediate in identity and bounded elsewhere.** Changing a user's roles or
  disabling the user bumps their session version. Identity checks the token's `sv` against its
  store on `/me` and the tenant admin routes, so it refuses an older token there at once. The
  other services, and identity's consent routes, check the signature, issuer, audience and expiry
  only: a revoked token keeps working there until it expires, ten minutes after issue by default
  (`CW_ACCESS_TOKEN_TTL_SECONDS`). A revocation list shared by every service would close that
  window; it is left out on purpose. A revoked service client gets no new token, and the tokens
  it holds run out the same way.
- **The second factor comes from the provider's `aal` claim.** Analysts, reviewers, admins and CA
  admins need a sign-in at `aal2`. The exchange refuses a one-factor sign-in for those roles with
  `identity-mfa-required` (403), and the web then sends the person to the provider to pass the
  second factor (TOTP in Supabase) and exchanges again. The token's `mfa` claim records it;
  services do not check it a second time.
- **Sign-in fails closed.** When identity cannot fetch the provider's keys and holds none, a new
  sign-in is refused with `identity-provider-unavailable` (503) rather than accepted unverified.
  Sessions already issued go on working: every service caches identity's key set for an hour and
  keeps the cached keys while identity is unreachable.
- **Keys rotate by `kid`.** `CW_IDENTITY_SIGNING_KEYS` is a list: the first key signs and every
  key is published. A new key goes in second, so it is published before it signs; it moves to the
  front once verifiers have fetched it, and the old key leaves once no token it signed is alive. A
  verifier that meets a `kid` it does not hold fetches the key set again, at most every 30
  seconds. The steps are in `docs/runbooks/secret-rotation.md`.
- **The switch is gradual.** `CW_AUTH_MODE` is `header` by default (the tenant from `x-tenant-id`,
  as before), `dual` (a bearer token is verified and enforced when a request carries one) or
  `token` (every route that reads the caller needs one, and shared secrets such as the
  rulebook's write and review tokens stop opening routes; probes, sign-in and the reads that are
  the same for everyone stay open, as listed in `packages/py-common/README.md`). `CW_ENV=prod` refuses any mode but `token` and refuses
  `CW_AUTH_PROVIDER=fake`, so staging runs `dual` and then `token` before production does.

The Supabase project is still a manual step (the list is in `services/identity/README.md`). The
adapter has been checked against synthetic tokens and recorded answers only, so this record stays
Proposed until staging signs a person in end to end through the project.
