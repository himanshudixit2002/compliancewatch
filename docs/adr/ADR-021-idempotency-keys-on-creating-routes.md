# ADR-021: Idempotency keys on the routes that create something

- **Status:** Proposed
- **Date:** 2026-10-07
- **Deciders:** the maintainer as product owner; Identity and Partner (owner of `services/identity`); Core Product

## Context

A client that does not hear back from a creating request cannot tell whether the thing was
created. On the routes that create a business, a registration, a location or an obligation
change, `py_common.idempotency` already answers that: the request carries an `Idempotency-Key`,
a retry with the same key and body gets the first answer back for 24 hours, the same key with
another body is a 422, and two requests racing on one key get a 409. Those routes required the
key from the day they existed, so no client ever called them without one.

`POST /v1/identity/billing/subscriptions` existed before the key. It starts a subscription with
the payment provider, which creates a customer and a subscription there before the identity
service stores anything. A retry without a key could therefore create a second subscription at
the provider and charge the tenant twice. The billing ledger work (package M3-4) made the route
take the key and record the start under it before the provider is called, so a retry never
reaches the provider again; a start that failed after the provider may have created the
subscription answers 409 `identity-subscription-start-pending` to the retry instead.

Making the header required is a breaking change to the committed spec: a client built against
the old shape gets 428 `idempotency-key-required` until it sends one. The only client is the web
app's billing form, which the same package changed to mint a key per attempt and keep it across
retries of that attempt.

## Decision

Every route that creates something a client would not want twice takes a required
`Idempotency-Key`, through `py_common.idempotency`, from the first version of the route where it
is new and as a recorded break where the route already exists. The subscription route is the
first such break. It is made in one step, with no period where the key is optional, because an
optional key would leave the provider double-charge open for exactly the clients that most need
the protection, the ones that retry blindly.

Who calls the operation: the web app's billing form, through the server layer (ADR-019). How it
moves: it sends a fresh key on each attempt and the same key on a retry of that attempt. When the
old shape goes: with the package that makes the break; there is no deprecation window, since no
third-party client exists and the public API (`public.v1.json`) does not expose the route.

## Consequences

- A client that omits the key gets 428 with the problem `idempotency-key-required`, which names
  the header, rather than a silent second charge.
- A key is scoped to the tenant and kept for 24 hours; `py_common.idempotency`'s purge removes
  older keys.
- Later creating routes follow the same rule, and a route that gains the key after it shipped
  adds its own row to `packages/contracts/openapi/BREAKING.md` citing this ADR, so each break is
  visible in review.
- The web app's forms mint keys per attempt (`docs/web/decisions.md`), never per render, so a
  second deliberate submission after a success is a new request.
