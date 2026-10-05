# Public API changelog

The public API is `public.v1.json`, which `make openapi-public` builds from the operations the
services tag `public`. Its version is `info.version` in `public.meta.json` and follows semver:
a new operation, or a new optional field or parameter, is a minor bump; a fix to wording or
documentation is a patch; a break (see `BREAKING.md`) is a major bump and a new `public.v2.json`
next to this one. The change that bumps the version adds its section here, and the build fails
while the version in `public.meta.json` has no section.

## 0.4.0

A business's obligations, from the obligation service:

- `GET /v1/businesses/{business_id}/obligations` lists the obligations kept for one profile node
  of the tenant (`business_id`: the business's legal entity, as in `/v1/businesses`, one of its
  registrations, or a location; a GSTIN's returns are kept for its registration), a page at a
  time (`limit` up to 200 and `cursor`), by due date with the ones without a date last, then by
  id. `status` keeps the given statuses (repeat it for several) and `due_from` and `due_to` the
  obligations due on those days in India, both included; a window longer than 366 days, or one
  that ends before it starts, is a 422. Each item is an obligation as the detail answers it,
  with the facts of its rule version (title, rule key, seed status, the approvers and when it
  was published) and the verified citations of its clause, without the history and the
  comments; `rule_version` is null and `citations` empty for a version the service has not kept
  yet, which the detail reads from the rulebook. 404 when the tenant has no such node, 503 when
  the profile service cannot say. Every tenant member role may read it.

A CA firm's bulk notification, from the notification service:

- `POST /v1/notification/bulk` sends the change card of one published change (`rule_version_id`)
  to the firm's affected clients (`business_ids`, 1 to 500, each once: the businesses of the
  change's impact) with `kind` `change_card`. Each business gets the card about its first open
  obligation of the change, queued for the client's own people who follow it (an owner or
  staff; the firm's own people hear in their daily digest), through the usual quiet hours and
  batching. A person who has the card of that change for that business already, from the change
  itself or an earlier request, gets nothing more: one change, one card per person and business.
  It answers 201 with the businesses by outcome (`queued`, `skipped_duplicate`,
  `skipped_no_recipient`, `skipped_not_affected`, each business counted once), the cards queued
  (`notifications_queued`) and each business's outcome, and it writes the audit entry
  `notification.bulk`. Only `ca_admin` and `ca_staff` may call it. It requires an
  `Idempotency-Key` header (428 without one), and a retry with the same key and body gets the
  first answer back; 503 while the flag `notification.bulk` is off or when the obligation
  service cannot answer.

Asking a question, from the qa service:

- `POST /v1/qa` is the public face of `POST /v1/qa/ask`, with the same body and answer: a
  question about one business (`business_node_id`, any profile node of the tenant) on a date
  (`as_of`, today in India when absent), answered in layers, cheapest first, as `answered` with
  citations whose quotes were checked against their clauses, or `not_covered` with a fixed
  sentence and the reason. `layers` lists every layer that ran and `layer` the one that decided.
  Every tenant member role may ask; asking creates nothing, so it takes no Idempotency-Key.
  The answer has no confidence and no related obligations, which the guide's example shows:
  the service does not produce them. A cited clause is the new schema `AnswerCitationOut`
  (clause, document and quote), named so beside the obligation's `CitationOut`.

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
