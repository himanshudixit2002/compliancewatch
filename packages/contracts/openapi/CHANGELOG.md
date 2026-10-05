# Public API changelog

The public API is `public.v1.json`, which `make openapi-public` builds from the operations the
services tag `public`. Its version is `info.version` in `public.meta.json` and follows semver:
a new operation, or a new optional field or parameter, is a minor bump; a fix to wording or
documentation is a patch; a break (see `BREAKING.md`) is a major bump and a new `public.v2.json`
next to this one. The change that bumps the version adds its section here, and the build fails
while the version in `public.meta.json` has no section.

## 0.3.0

The changes feed, from the rulebook, and the impact of a change, from the applicability engine.
Every tenant member role and the regulatory team's roles (analyst, reviewer, admin) may read the
feed, so `x-roles` may now name the regulatory roles too; the impact is for the tenant's members:

- `GET /v1/changes` lists the published changes to the rulebook, newest first, a page at a time
  (`limit` up to 100 and `cursor`), optionally since a date (from the start of that day in India)
  or a date-time, and of one regulator. One item per change the rule events announced: a version
  published, superseded or withdrawn, or a due date a published version moved
  (`deadline_changed`, about the version whose date moved, with the period and the new date).
  Each carries the version's rule key, title, dates, regulator and status, its seed status
  (needs_review until an analyst reviews it), the approvers of the round it was published from
  with `published_at`, its verified citations (clause, document and quote) and the versions it
  supersedes, corrects, withdraws or whose due dates it moves. The feed is the same for every
  tenant and needs no tenant.
- `GET /v1/changes/{rule_version_id}/impact` answers what a change means for the caller's tenant:
  each of its businesses with its latest decision of the version (result, confidence, whether it
  needs review, when and why it was decided, and every predicate's outcome in words), grouped
  under the client they belong to, the legal entity at the top of their lineage, a page of
  clients at a time (`limit` and `cursor`); `result=applies` keeps the affected ones. It also
  counts the tenant's businesses by result and gives the status and counters of the version's
  fan-out over every tenant.

## 0.2.0

Obligation tracking, from the obligation service. The four operations serve the routes the web app
calls under `/v1/obligation/obligations/{obligation_id}`, and every tenant member role may call
them:

- `GET /v1/obligations/{obligation_id}` answers one obligation with the facts of its rule version
  (title, rule key, whether the seed rule is reviewed, the approvers of the round it was published
  from and when), the verified citations of its clause, its history and its comments, oldest
  first. The obligation itself gains `profile_version` and `assignee_id`.
- `POST /v1/obligations/{obligation_id}/status` starts, completes or waives an obligation; a
  waiver needs a reason of at least ten characters. 409 when it is closed, 422 when its status
  does not allow the action.
- `PUT /v1/obligations/{obligation_id}/assignee` gives an obligation to a user of the tenant, or
  to nobody with null; a verified caller can only name an active user of the tenant (422).
- `POST /v1/obligations/{obligation_id}/comments` adds a comment and answers 201.

Each change requires an `Idempotency-Key` header and answers 428 without one.

## 0.1.1

Documentation of verified access tokens, with no change to the operations:

- Every business operation documents 403: a caller whose access token lacks a tenant member
  role, or a service without the `tenant:act` scope, or an `x-tenant-id` header naming another
  tenant than the user's token.
- `x-tenant-id` says that a user's token names the tenant and a service names it in the header.
- The `bearerAuth` scheme says when a token is required (`CW_AUTH_MODE` token, as in
  production) and that header mode takes the tenant from `x-tenant-id` instead.

## 0.1.0

First version, from the profile service:

- `POST /v1/businesses` creates a business from its GSTIN, or from its PAN alone, and answers
  the GSTIN pre-fill and the first onboarding question. It requires an `Idempotency-Key`
  header and answers 428 without one.
- `GET /v1/businesses` lists the tenant's businesses by name, a page at a time, with a search
  over name, PAN and GSTIN.
- `GET /v1/businesses/{business_id}` and `PATCH /v1/businesses/{business_id}` read and update
  one business, all changes or none.
- `GET /v1/businesses/{business_id}/onboarding` answers the next onboarding question with its
  wording and labelled options, and how many are answered.
- `POST /v1/businesses/{business_id}/registrations` adds a GSTIN registration to a business. It
  requires an `Idempotency-Key` header and answers 428 without one.
- `GET /v1/ontology` answers the profile attributes with their questions, value labels and the
  rule operators per type, with an ETag.
