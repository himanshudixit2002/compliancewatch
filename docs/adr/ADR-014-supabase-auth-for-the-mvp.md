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
