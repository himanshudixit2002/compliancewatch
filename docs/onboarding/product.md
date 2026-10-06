# The local product

`make product` brings up the working product on this machine: ADR-013's one deployable
(`composition/mvp`, its app and worker processes) with Kafka and Temporal on, on the dev stack,
and the web app. `make product-seed` fills it with two synthetic tenants and a synthetic
publication of the seed rules the golden world cites, and `make product-check` proves that a
published rule becomes decisions, obligations with citations and a change card, that a
business made or changed in the profile is decided again by itself, that a rule published
behind the fan-out hold reaches every business once the hold is released, that a sweep run a
few days before a due date sends a reminder, that a member can start, assign, complete and
comment on an obligation, a change sent twice with one Idempotency-Key made once, and that the
changes feed lists the publication with its synthetic approvers, the impact of the change lists
the CA firm's affected client, and a dry run counts what the fan-out decided while writing
nothing but its audit row, and that the public listener lists a business's obligations a page
at a time, answers a question from them with citations, and sends a CA firm's bulk change card
once per change and person, that the pipeline lists its sources, refuses to crawl while
crawling is off, keeps the statutes upload-only and refuses an upload that is no document,
that every seed draft waits in the rulebook's review queue, where a task is claimed and read, and
that the pipeline's triage routes answer and its rule extraction asks the gateway's fake model
with the registered prompt, ingesting nothing. On a database made for the run (CI), it also
proves that a withdrawn rule closes its obligations in both tenants and sends withdrawal notices.

```bash
make product                 # make dev, make migrate, make product-role, the seed calendar, then
                             # cw-mvp serve, cw-mvp worker and next dev; waits until all answer
make product-seed            # synthetic tenants, the demo publication, the first decisions
make product-check           # health, honesty, loop, isolation, recompute, fanout, reminders,
                             # tracking, changes, public, sources, review, extraction: exit 0
                             # means accepted
                             # (rollback reports itself skipped; CI runs it with
                             # ARGS="--destructive")
make product-e2e             # the web app's real-data journey on it (Playwright project product)
make product-logs PROC=worker   # app, worker or web; FOLLOW=0 prints the end and returns
make product-down            # stops only what make product started
```

`WEB=0` leaves the web app out, `WEB_PORT=3400` puts it on another port. Run
`make product` again at any time: it starts only what is not running. Everything it writes stays
in the dev database until `make dev-reset`. `make product-image` runs the same product from the
deployable's image instead, as CI does (below).

## What runs

| Process | Where | What |
| --- | --- | --- |
| app | public listener `127.0.0.1:8000`, internal listener `127.0.0.1:8080` | `cw-mvp serve`: every service's API in one process ([composition/mvp/README.md](../../composition/mvp/README.md)). The internal listener serves every route; the web app and `cw-product` call it |
| worker | health `127.0.0.1:8081` (`/health`, `/loops`) | `cw-mvp worker` with `CW_WORKER_KAFKA_ENABLED` and `CW_WORKER_TEMPORAL_ENABLED` on: the outbox relay of every schema, the engine's consumers of profile.updated (group `applicability-engine.profiles`, recompute on) and of rule.published and rule.withdrawn (group `applicability-engine.rules`, fan-out on), obligation's consumers of applicability.decided (group `obligation.decisions`) and of the rule events (group `obligation.rules`, on), notification's consumer of the obligation events (group `notification.obligations`), the notification dispatcher and retention sweep, obligation's reminder sweep and daily rolling window, the rulebook's transition sweep, and the Temporal task queues of the engine's fan-out (`applicability`) and the pipeline |
| web | `WEB_PORT` (3000) | `next dev` with every `CW_WEB_*_URL` at the internal listener, building into `apps/web/.next/product` |

Before starting them, `make product` runs `make dev` (the compose stack; nothing happens when it
already runs), `make migrate`, `make product-role` and `make seed SERVICE=rulebook` (the thirteen
seed rules as drafts). Pids and logs are in `var/product`; `make product-down` stops the
processes whose pids it recorded there, with their children, and nothing else.

The services connect to Postgres as `cw_app`, a role that owns nothing and is not a superuser,
so row-level security keeps the tenants apart as it does in a deployment. `make product-role`
creates the role on the running stack and grants it the service schemas
(`infra/dev/postgres/50-app-role.sql`, safe to repeat). `make migrate`, `make run` and
`make web-stack` still connect as `cw`, the image's superuser, which bypasses every policy.

The settings that make this the product are passed by the make targets, never as a default in a
settings class or the flag registry: header auth, both listeners on `127.0.0.1`, the worker's
health on `PRODUCT_WORKER_PORT` (8081, since 8001 is identity's under `make run` and
`make web-stack`), the worker's two switches and the reminder sweep and rolling window on, the
engine's recompute on profile.updated on (`CW_APPLICABILITY_RECOMPUTE_ENABLED`) with the
rulebook's in-force listing cached for five seconds (`CW_APPLICABILITY_ENGINE_RULES_CACHE_SECONDS`),
the engine's fan-out of rule.published on (`CW_APPLICABILITY_FANOUT_ENABLED`), obligation's
consumer of the rule events on (`CW_OBLIGATION_RULE_EVENTS_ENABLED`), a CA firm's bulk change
card on (`CW_NOTIFICATION_BULK_ENABLED`), rule publishing on with the placeholder tokens
`local-write-token` and `local-review-token` (not secrets; values in `.env` win), the profile's
static GSTIN lookup, the notification sink in place of the real channels with a five-second
batching window, message links to the product's web app, and the pipeline's crawl off.

### The crawl stays off

A crawl reads the live regulator sites (`services/pipeline/README.md`, "The crawl"), and the local
product never does: `make product` passes `CW_PIPELINE_CRAWL_ENABLED=false` whatever `.env` says,
and the image product (`docker-compose.yml`, `x-mvp-env`) and CI do the same. The worker still adds
the built-in sources to the pipeline's store when it starts, so the source manager on the internal
listener lists them, each healthy and never fetched:

```bash
curl -s http://127.0.0.1:8080/v1/pipeline/sources | jq '.items[] | {key, status, freshness}'
```

An admin's fetch (`POST /v1/pipeline/sources/{key}/fetch` with the shared write token
`local-write-token`) answers 503 `pipeline-crawl-disabled` and starts nothing. No source of the
product is pointed at recorded fixtures, so nothing here crawls them either: the crawl over
recorded notifications runs in `tools/demo/tests/unit/test_pipeline_crawl_flow.py` and the
pipeline's crawl workflow tests.

The statutes (`cgst_act`, `cgst_rules`, `igst_act`) are upload-only sources (`listable` false):
no crawl lists them, and their documents come only from an admin's upload
(`POST /v1/pipeline/sources/{key}/uploads`, multipart, with the same token). A stored document is
never deleted, so the product check uploads nothing it keeps: it sends a text file, which is
refused 415 `pipeline-upload-unsupported` before anything is stored, and reads the task queue
(`GET /v1/pipeline/tasks`). An upload, the manual-parse task of a document no parser reads and
its transcript run in `tools/demo/tests/unit/test_manual_parse_flow.py`.

### The rule extraction is on, and asks the fake model

`make product` passes `CW_PIPELINE_EXTRACTION_ENABLED=true`: the ingest classifies each parsed
document and, for a notification, circular or act amendment it registered (which needs
`CW_PIPELINE_KNOWLEDGE_ENABLED`, off unless `.env` turns it on), extracts its rule candidate
through the llm-gateway (`services/pipeline/README.md`, "Extraction in the workflow"). The
product's gateway answers from its fake model unless `.env` names another provider: deterministic
and free, a placeholder that cites no clause, so a candidate made here is stored unparseable for
an analyst. The product ingests nothing by itself, so nothing is extracted unless someone uploads
a document to it. The check's extraction step uploads nothing either: it proves the triage routes
and asks the gateway with the registered prompt about a synthetic notification it stores nowhere,
and it reports itself skipped when the gateway answers from a real model. A recorded notification
becomes a classified, extracted candidate in `tools/demo/tests/unit/test_extraction_flow.py`.

## The product from its image

`make product-image` runs the product from the image a deploy ships
(`composition/mvp/Dockerfile`, [composition/mvp/README.md](../../composition/mvp/README.md)), in
the compose profile `mvp` on the dev stack, with the settings `make product` passes its processes:

```bash
make product-image           # make dev, the image, make product-role, then mvp-release, mvp-app
                             # and mvp-worker in containers, and the seed calendar from the image
make product-seed            # unchanged: the same ports, cw_app and var/product/sink.jsonl
make product-check
make product-image-logs PROC=worker   # app, worker or release; FOLLOW=0 prints the end and returns
make product-image-down      # removes the three containers; the dev stack keeps running
```

| Container | What |
| --- | --- |
| `mvp-release` | `cw-mvp release`, once, before the others start: every service's migrations as the database's owner (`CW_MIGRATION_DATABASE_URL`, the dev stack's superuser), then the topics of `composition/mvp/topics.toml`. It prints what it migrated and created, and a second run changes nothing |
| `mvp-app` | `cw-mvp serve`, published on `127.0.0.1:8000` and `127.0.0.1:8080`, connecting as `cw_app` |
| `mvp-worker` | `cw-mvp worker`, calling the app at `http://mvp-app:8080`; its health published on `127.0.0.1:8081` |

`make product-image` builds the image first (`make mvp-image`; `MVP_BUILD=0` uses the one there,
as CI does after building it with buildx), creates `cw_app` before the release (its default
privileges cover the tables the release makes), and loads the seed calendar's drafts with the
image's `rulebook-seed` once the app is up. The containers mount `var/product` and run as your
user (`CW_MVP_USER`, your uid and gid), so the sink file they write is yours to read, as
`make product-check` does. The repo's `.env` is not passed to them: its URLs name `localhost`.
`docker-compose.yml` (`x-mvp-env`) holds their settings, the rulebook's tokens from `.env` when it
sets them.

It and `make product` share the ports, so one runs at a time; `make product-image` refuses while
`make product`'s processes run. Both share the dev database and broker, and so the consumer
groups' offsets: either picks up where the other stopped. On the dev stack the release reports
the topics that Redpanda created by itself before (one partition, a week of retention) as
differing from the file; it leaves them as they are.

CI's dev-stack job builds the image with buildx and the GitHub Actions cache, runs
`cw-mvp release` on its fresh database and broker, then `make product-image MVP_BUILD=0` (whose
release changes nothing), `make product-seed`, `make product-check ARGS="--destructive"` and the
web journey (`make product-e2e`) against it. The web journey only talks HTTP to the internal
listener, so it costs the same against the image as against the local processes. `make product`
stays the development path: it runs the checkout's code as it is, with no image to build.

## From a published rule to a change card

1. `cw-product publish` takes a seed rule from draft to published as synthetic analysts (below);
   `rule.published` goes to the rulebook's outbox.
2. The engine's rules consumer starts the version's fan-out, which decides it for every business
   its directory lists (below); `cw-product evaluate` also asks the engine to decide every
   published rule for every seeded registration, and stays as an operator tool. The engine also
   decides by itself whenever a profile changes (below). Each decision and its
   applicability.decided event are stored together.
3. The worker's relay publishes the event; obligation's consumer materialises the periods of an
   applying rule still due on the decision's day, through the period it falls in and the next
   (obligation.created each): a monthly return decided on 6 October gets September, due 20
   October, October and November; decided after the 20th, October and November. It closes
   nothing for one that does not apply.
4. Notification's consumer queues one change card per rule version, business, recipient and
   channel (the events of the other periods are duplicates), due after the five-second window.
5. The dispatcher (every five seconds) renders it. The synthetic owner hears on WhatsApp first and
   email second, has never written to the business number, and every template is a draft, so
   the WhatsApp attempt is refused exactly as the Cloud API adapter refuses it (outside the
   24-hour window, template not approved) and the email fallback goes at once.
6. The sink records both, `refused` and `sent`, in `var/product/sink.jsonl`.

The whole chain takes about ten seconds; `make product-logs PROC=worker` shows each step
(`obligation.decision_applied`, `notification.event_queued`, `notification.dispatched`).

## From a profile change to new decisions

Every change to a business in the profile (the owner's answers, the GSTIN pre-fill, a business
created through `POST /v1/businesses` or changed with `PATCH /v1/businesses/{id}`) writes
profile.updated to profile's outbox. The worker's relay publishes it and the engine's consumer
(group `applicability-engine.profiles`) recomputes:

1. It reads, with no database transaction open, the changed node's snapshot and, for a legal
   entity, the registrations under it, then each node's snapshot and the rule versions in force
   for the node's level (today in India, and those taking effect within 92 days).
2. In one transaction with the event's inbox row it records the nodes in the business directory
   and stores a decision of every rule version for every node, with the trigger
   `profile_updated`. A decision publishes applicability.decided when it applies, or when its
   result differs from the previous decision of its business and rule version; an unchanged
   not_applicable or unsure one is stored quietly. Handling the same event again stores nothing.
3. Obligation's consumer makes the obligations of a rule that applies and closes, with
   `profile_changed`, the open ones of a rule that no longer applies.

A decision the engine cannot settle on a free-text predicate opens a review item for the
regulatory team (`GET /v1/applicability-engine/review-items` and
`POST /v1/applicability-engine/review-items/{item_id}/resolve` on the internal listener, the
tenant in `x-tenant-id`). An unanswered question makes a decision unsure without a review item:
the owner answers it and the next change decides again. None of the four seed rules has a
free-text predicate.

The engine's consumer is a new consumer group, and a new group reads a topic from its earliest
offset: its first run recomputes every profile.updated the broker still holds, those of the web
stack's tenants included (with `make web-stack STORE=postgres`, which shares the database). To
start it at the end of the topic instead, before the first `make product` with it:

```bash
docker compose exec -T redpanda rpk group seek applicability-engine.profiles --to end \
  --topics profile.updated --allow-new-topics
```

## From a publication to every business: the fan-out

`rule.published` reaches the engine's consumer (group `applicability-engine.rules`). It drops the
rulebook client's in-force cache, reads the version, starts the workflow
`applicability-fan-out-<rule version id>` on the Temporal task queue `applicability` and records
the run (`GET /v1/applicability-engine/fan-outs/{rule_version_id}` on the internal listener). The
workflow decides the version for every node of its level in the business directory, 1,000 at a
time, one tenant group at a time, with the trigger `rule_published`; obligation's consumer then
makes the obligations of each decision that applies. A version fans out once.

At every batch boundary the run obeys the global hold (`PUT /v1/applicability-engine/fan-out-hold`
with `held` and a reason) and its own pause, resume and cancel routes; each control is audited in
`audit.event`, of no tenant. A superseding version that flips more than 2% of at least 200
compared businesses pauses itself. [docs/runbooks/fan-out-control.md](../runbooks/fan-out-control.md)
has the controls and what to do when a run is held, paused or failed.

The directory lists the nodes the engine heard of through profile.updated since its consumer
group started, so a fan-out reaches those. A new consumer group reads its topics from the earliest
offset: the first run of `applicability-engine.rules` fans out every version the broker still
holds a rule.published for (on the dev stack, the GSTR-3B rules published before). To start it at
the end instead, before the first `make product` with it:

```bash
docker compose exec -T redpanda rpk group seek applicability-engine.rules --to end \
  --topics rule.published,rule.withdrawn --allow-new-topics
```

## From a withdrawal to closed obligations

The rulebook writes rule.withdrawn, rule.superseded and rule.deadline_changed without a tenant.
Obligation's consumer (group `obligation.rules`) reads the version fresh at the rulebook, caches
it in `obligation.rule_version_ref`, and applies the event to every tenant of the
`obligation_tenant` directory, one unit of work per tenant in the consumer's transaction, each
under its own tenant setting:

1. rule.withdrawn closes the version's open obligations with `rule_withdrawn`
   (`obligation.closed` and a change row each); notification's consumer turns each closure into
   an `obligation_withdrawn` notice, sent through the sink for the business owner and held for
   the CA firm's 09:00 IST digest.
2. rule.superseded closes, with `rule_superseded`, the open obligations the newer version takes
   over (the periods that end after it takes effect), and the earlier periods stay open.
3. rule.deadline_changed moves the period's open obligations to the new date
   (`obligation.rescheduled`, an `obligation_deadline_extended` notice).
4. rule.published only fills the cache: the obligations of a new version come with the
   engine's fan-out decisions.

A decision that reaches obligation after the version was withdrawn or superseded (a fan-out batch
in flight, a consumer behind on its topic) is refused by the guard, which reads the cache and the
rulebook: nothing for a withdrawn version, only the periods a superseded one still governs, and
nothing for a version without a verified citation. The worker logs `obligation.decision_guarded`
and counts `obligation_guard_refusals_total`. Every use case is idempotent, so a replayed rule
event changes nothing more.

The new consumer group reads its topics from the earliest offset on its first run: on the dev
stack that is the rule.published events of the seed rules already published, which only fill the
cache. The rolling window runs daily at 02:30 IST and makes the periods that entered the window
for every business whose latest decision applies; `obligation-sweep --once` runs it and the
reminder sweep at once (`--now` and `--tenant`, local and test only, are how the check's
reminders step runs it).

## Tracking an obligation

A member of the tenant works an obligation through the obligation service's routes, each under
`/v1/obligation/obligations/{obligation_id}` (and in the public API under
`/v1/obligations/{obligation_id}`):

1. `GET` answers the obligation whole: the facts of its rule version from
   `obligation.rule_version_ref` (title, rule key, `reviewed` false while the seed rule needs
   review, and `approved_by` with `published_at`, the reviewed-by line), the verified citations
   of its clause, its history from `obligation.obligation_change` and its comments, oldest first.
2. `POST .../status` with `start`, `complete` or `waive` (a waiver needs a reason of at least ten
   characters); completing and waiving publish obligation.closed, which sends no message.
3. `PUT .../assignee` gives it to a user of the tenant, or to nobody. With a verified caller the
   obligation service asks identity whether the user belongs to the tenant; in the product's
   header mode nobody is verified, so the assignee is kept as named.
4. `POST .../comments` adds a comment (`obligation.obligation_comment`, append-only).

Each change takes an `Idempotency-Key` (kept in `obligation.idempotency_key`), appends to the
history and writes an `audit.event` row in the same transaction (`obligation.status.start`,
`.complete` or `.waive`, `obligation.assign`, `obligation.comment`, the last naming the comment
and not its text). In header mode those rows name the actor `system:obligation`.

## Changes, their impact and dry runs

The public API's changes feed, `GET /v1/changes` (the rulebook), lists every change the rule
events announced, newest first: a version published, superseded or withdrawn, or a due date a
published version moved. Each item carries the version's rule, dates, regulator and status, its
seed status (needs_review for every seed rule here, since the publication is synthetic), the
approvers of the round it was published from (the two synthetic reviewers) and its verified
citations. It is the same for every tenant and needs no `x-tenant-id`:

```bash
curl -s 'http://127.0.0.1:8080/v1/changes?limit=5'
```

`GET /v1/changes/{rule_version_id}/impact` (the engine) answers what one change means for the
tenant in `x-tenant-id`: each of its businesses with its latest decision of the version, under
the client it belongs to, the counts by result and the version's fan-out. With `result=applies`
it is a CA firm's affected clients:

```bash
curl -s 'http://127.0.0.1:8080/v1/changes/<gstr9_annual version id>/impact?result=applies' \
  -H 'x-tenant-id: 00000000-0000-4000-8000-0000000d0002'
```

An admin's dry run, `POST /v1/applicability-engine/dry-runs` (the engine, internal listener only
in header mode), evaluates a version in any status, or a specification, against the business
directory, of one tenant when the scope names one, and answers the counts by result and by
deciding attribute with sample decisions. It stores nothing but its `applicability.dry_run` row in
`audit.event`, and refuses a scope wider than `CW_APPLICABILITY_DRY_RUN_MAX` (2,000) businesses:

```bash
curl -s -X POST http://127.0.0.1:8080/v1/applicability-engine/dry-runs \
  -H 'content-type: application/json' \
  -d '{"rule_version_id": "<version id>", "scope": {"tenant_id": "00000000-0000-4000-8000-0000000d0002"}}'
```

## The public API

The public listener (`127.0.0.1:8000`) serves the routes `composition/mvp` classes public, the
public API (`packages/contracts/openapi/public.v1.json`, 0.4.0) among them, and answers an
internal route 404 `route-not-found` (admin routes too, in header mode). Besides the businesses,
the tracking routes and the changes feed, the public API lists one profile node's obligations a
page at a time, with each one's rule title, review state and verified citations (a GSTIN's
returns are kept for its registration; `status` and `due_from`/`due_to` filter, a window of at
most 366 days):

```bash
curl -s 'http://127.0.0.1:8000/v1/businesses/<registration id>/obligations?status=open&limit=20' \
  -H 'x-tenant-id: 00000000-0000-4000-8000-0000000d0001'
```

`POST /v1/qa` answers a question about one node. With the knowledge graph off, as here, the
structured layer answers "When is my GSTR-3B due?" from the registration's obligations, with the
rule's verified citations; a question it cannot answer goes to the clause search, which runs on the
gateway's fake model here:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/qa -H 'content-type: application/json' \
  -H 'x-tenant-id: 00000000-0000-4000-8000-0000000d0001' \
  -d '{"question": "When is my GSTR-3B due?", "business_node_id": "<registration id>"}'
```

`POST /v1/notification/bulk` sends a CA firm's change card to the clients a change affects, for
the clients' own people (an owner or staff who follows the client; the firm's own people hear in
their daily digest), once per change, business and person, with an `Idempotency-Key`.
`make product` turns its flag on (`CW_NOTIFICATION_BULK_ENABLED=true`); the seeded firm has no
client contact, so a bulk notification of its own answers `skipped_no_recipient` until one is
registered, as the check's public step does for its run:

```bash
curl -s -X POST http://127.0.0.1:8000/v1/notification/bulk -H 'content-type: application/json' \
  -H 'x-tenant-id: 00000000-0000-4000-8000-0000000d0002' -H "Idempotency-Key: $(uuidgen)" \
  -d '{"rule_version_id": "<gstr9_annual version id>", "business_ids": ["<client registration id>"], "kind": "change_card"}'
```

### The sink

`CW_NOTIFICATION_CHANNELS=sink` replaces both channels with
`notification.infrastructure.sink.SinkChannel`, which records each message as a JSON line in
`CW_NOTIFICATION_SINK_PATH` instead of sending it; the settings refuse it unless `CW_ENV` is local
or test. The delivery rules are the service's own and hold unchanged: consent and suppressions,
dedupe, quiet hours, batching, digests, retries and fallbacks. The 24-hour window belongs to the
adapter, and the sink applies it as the Cloud API adapter does. Draft templates are therefore
handled as on the real channels: on WhatsApp only inside the window, as free text; on email
always, as rendered text. Each line names the template's status, so a recorded draft is never
taken for an approved message, and none of it reaches a person.

## What the seed creates

All of it is synthetic and fixed (`tools/demo/src/cw_demo/product/tenants.py`), so a second run
finds it again:

| Tenant | Id | Businesses | Applies (of the four cited seed rules) |
| --- | --- | --- | --- |
| Demo Traders (synthetic), a business | `00000000-0000-4000-8000-0000000d0001` | Demo Traders Bengaluru (synthetic), the demo GSTIN 29ABCDE1234F1Z5, a monthly filer | gstr3b_monthly, gstr9_annual |
| Demo CA Associates (synthetic), a CA firm | `00000000-0000-4000-8000-0000000d0002` | Demo Client One Bengaluru (synthetic), the demo GSTIN, quarterly, a turnover of 2 to 5 crore; Demo Client Two Delhi (synthetic), the made-up 07ZZZZZ9999Z1Z5, quarterly | group A of the quarterly GSTR-3B and gstr9_annual; group B |

For each tenant the seed records the consents of its owner (or the firm's admin) through the API,
registers the GSTINs with the pre-fill and the answers, and registers a recipient with a phone
number (+91 followed by zeros, which no Indian mobile number starts with) and a mailbox on the
reserved `.invalid` domain, both opted in with no quiet hours of their own, so the loop completes
at any hour. The firm's admin hears by the daily digest (09:00 IST), as every CA firm's people do.

## Honesty

- Only the four seed rules `evals/golden/qa/kag/world.yaml` cites from recorded quotes can be
  published: gstr3b_monthly, gstr3b_quarterly_group_a, gstr3b_quarterly_group_b (the default)
  and gstr9_annual (`make product-seed ARGS="--rule gstr9_annual"`, or
  `cw-product publish --rule gstr9_annual`, which the check's fanout step runs once behind the
  hold). The other nine stay drafts.
- The recorded CBIC notifications the world uses are registered through the rulebook's pipeline
  write route, and the rulebook verifies every quote against the stored clause.
- Each version is submitted by "Demo analyst (synthetic)", tagged high impact, approved by "Demo
  reviewer one (synthetic)" and "Demo reviewer two (synthetic)" with `synthetic: true`, and
  published; every note says "synthetic demo publication - not an analyst review". A synthetic
  approval leaves the version's seed status at needs_review, and the rulebook accepts one only
  where `CW_ENV` is local or test. Nothing is marked reviewed.
- `cw-product` refuses to run unless `CW_ENV` is local or test and `CW_AUTH_MODE` header or dual.
- A published version stays published: the rulebook has no way back for it short of withdrawing
  it, which ends it, and only `make dev-reset` gives a dev database without it. The check's
  rollback step withdraws gstr9_annual, so it runs only with `--destructive`, which the CI
  dev-stack job passes on its fresh database; never pass it against the shared dev database,
  where the fanout step relies on gstr9_annual staying published.

## Signing in on the web

After `make product-seed`, open the sign-in page of the product's web app, choose "Use the last
seeded tenant" (it reads `var/seed/last.json`, which the seed writes in the shape the web seed
does), a role and a display name, and sign in: the business page of Demo Traders (synthetic)
opens, with its obligations, calendar, changes and (with `CW_WEB_FLAG_QA_ENABLED=true` in
`apps/web/.env.local`) Ask as tabs ([docs/web/obligation-pages.md](../web/obligation-pages.md)).
For the CA firm, choose the tenant kind CA firm and paste its id from the table above.

`make product-e2e` runs the web app's real-data journey on the running product: it builds the app
into `apps/web/.next/e2e-product`, starts it with `next start` on `PRODUCT_E2E_PORT` (3400) against
the internal listener, and runs the Playwright project `product` (signed in as the seeded business
tenant: the obligations in the list and the calendar, an obligation's citations and synthetic
approvers, a probe business's first obligation started, completed and commented on, the annual
return's change applying, and a cited answer). The CI dev-stack job runs it after `make
product-check`. Each run adds one synthetic probe business to the database, as the check does.

Cookies ignore the port. With `make web-dev` on `localhost:3000`, run the product's app on
another port and open it at `127.0.0.1` (`make product WEB_PORT=3400`, then
`http://127.0.0.1:3400/sign-in`), so the two sessions stay apart; the product's dev server
accepts `127.0.0.1` for that. `apps/web/.env.local` gives the app its session secret and the
fake sign-in provider; without them, `make product` sets the fake provider and a secret for the
run.

## The check

`cw-product check` runs its steps in order; each one waits up to `--timeout` seconds (30) for what
the worker does a few seconds after the API answers, and a failed step does not stop the next.

| Step | Proves |
| --- | --- |
| health | `/ready` on the internal listener lists every service's checks as ok, the public listener answers, and the worker's `/loops` runs the five consumer groups, the outbox relays (the pipeline's, which publishes document.discovered, among them), the dispatcher, the reminder sweep, the rolling window and the `applicability` and `pipeline` task queues |
| honesty | every published seed rule is one the world cites and reads needs_review, every other seed rule is a draft, nothing is marked reviewed, and the golden world and its cases are drafts |
| loop | evaluates the business tenant, then waits for the decisions its answers call for, an obligation of each rule that applies whose version cites a verified clause, and a change card about the business sent through the sink (with its line in the sink file) |
| isolation | the CA firm reads none of the business tenant's decisions, obligations, notifications or business, and the other way round |
| recompute | makes a new synthetic business in the business tenant with `POST /v1/businesses` (a monthly GSTR-3B filer in Karnataka with a made-up GSTIN, named with the time it was made), then waits for its gstr3b_monthly decision `applies` with the trigger profile_updated and its obligations; changes its registration to the quarterly scheme with `PATCH /v1/businesses/{id}` and waits for the decision `not_applicable`, the monthly obligations closed with `profile_changed` and the quarterly group A obligations. It never calls `cw-product evaluate`; every decision of the business comes from profile.updated, and no review item opens for it. Each run makes one more business, since a closed obligation stays closed and only a new business shows the whole change again |
| fanout | while gstr9_annual is not published: sets the fan-out hold, publishes gstr9_annual as `cw-product publish --rule gstr9_annual` does, waits for its run to stand `held` with nothing decided, releases the hold and waits for the run to complete. Once it is published (a second check on the same database): finds that run completed, resuming it first if an earlier check left it paused, and sets and releases the hold again. Then the run's counters must match the directory entries of the level, each synthetic registration the directory lists must have its gstr9_annual decision from the fan-out with the result its answers call for, the registrations it applies to must have GSTR-9 obligations in both synthetic tenants, and `audit.event` must hold the hold, the release and any resume the step made. A hold an interrupted check left is lifted first; anyone else's fails the step |
| reminders | runs `obligation-sweep --once --now <moment> --tenant <business tenant>` in the check's process, on the obligation settings of the product's worker, with the moment 5 days, 2 days or 12 hours before one of the business tenant's open obligations is due (the first lead whose threshold has not reminded it yet, so every run sees a new reminder), then waits for the reminder about that obligation to be sent through the sink, with its line in the sink file. The sweep and the window touch no other tenant |
| rollback | only with `--destructive` (CI), skipped otherwise: withdraws gstr9_annual through the rulebook's withdraw route as the first synthetic reviewer, then waits for every GSTR-9 obligation of both synthetic tenants to close with `rule_withdrawn`, and for the withdrawal notices: sent through the sink for the business tenant, held for the daily digest (or sent) for the CA firm. On a database where it was withdrawn already, it checks what followed |
| tracking | makes a new synthetic business in the business tenant with `POST /v1/businesses` (a monthly GSTR-3B filer, named "Tracking probe" with the time it was made) and waits for its gstr3b_monthly obligations from profile.updated; starts the first one due, assigns it to the tenant's synthetic owner, and sends the same complete twice with one Idempotency-Key: one closure, and the second answer is the first with `Idempotent-Replayed: true`. The detail must show the history created, started, assigned, closed, both synthetic reviewers in `approved_by` while the seed status stays needs_review, and verified citations; then a comment is added and listed. Each run spends a business of its own, so the seeded registration's obligations stay open for the reminders step and a later check passes again |
| changes | on the gstr9_annual version the fanout step published: `GET /v1/changes` (read from its `published_at`) must list its publication with both synthetic reviewers in `approved_by`, the seed status needs_review and verified citations; `GET /v1/changes/{id}/impact?result=applies` as the CA firm must list exactly the firm's registrations the answers call for, each under its client, with the fan-out completed; and a dry run of the version scoped to the CA firm must count what the firm's latest decisions of it count for the registrations the directory lists, every one decided and none skipped, write one `applicability.dry_run` row of no tenant (found by the request's correlation id) and not one decision, review item or outbox row of the firm. After the rollback step (CI) the publication stays in the feed and the dry run reads the withdrawn version |
| public | through the public listener: as the business tenant, `GET /v1/businesses/{id}/obligations` lists the seeded registration's obligations by due date, pages of one follow one another, each carries its rule's title, `status=open&status=in_progress` keeps those, a window of 367 days is a 422, and the CA firm reading it gets a 404. `POST /v1/qa` asks "When is my GSTR-3B due?" and must be answered by the structured layer with the first open monthly return due from today and verified citations; the CA firm asking gets a 404. As the CA firm, it registers a synthetic client contact (an owner on a `public-check-…@demo-ca-associates.invalid` mailbox, opted in, following the clients the change affects) and sends `POST /v1/notification/bulk` of gstr9_annual (of gstr3b_quarterly_group_a once the rollback step withdrew it) to the clients its impact lists: one card per client to the contact and none to the firm's admin; the same Idempotency-Key answers the same with `Idempotent-Replayed: true`, and a new key finds every card queued already. Each request that ran wrote one `notification.bulk` row of the firm (found by its correlation id), the contact's card goes through the sink, and the contact is removed (with any an interrupted check left). `POST /v1/notification/send` answers 404 on the public listener |
| sources | the pipeline's source manager on the internal listener lists the eight built-in sources with a name, regulator, cadence, status and freshness each; a fetch of a key no source has is refused as crawling off (with crawling on it would be a 404, and the step stops there without fetching a real source), then a fetch of `cbic_notifications` is refused the same way, 503 `pipeline-crawl-disabled`, and records no crawl run; the public listener answers the list 404 in header mode. No source of the product reads recorded fixtures, so no crawl runs here: `test_pipeline_crawl_flow.py` runs one. The statutes `cgst_act`, `cgst_rules` and `igst_act` read upload-only, `GET /v1/pipeline/tasks?status=open` answers, and an upload of a text file to `cgst_rules` is refused 415 `pipeline-upload-unsupported` with the source's document count unchanged (a stored document is never deleted, so the step keeps none; `test_manual_parse_flow.py` runs uploads and a manual parse) |
| review | `POST /v1/rulebook/review/tasks/seed` opens a review task for every seed draft that has none waiting, and a second request opens none; every seed draft that needs review then has a task waiting (open or claimed), and a task waiting on a version the publish routes moved on (a seed rule `cw-product publish` published) is reported. The synthetic check analyst (`00000000-0000-4000-8000-00000000a004`) claims one task, the one it holds from an earlier run or the first open draft, and claiming it again changes nothing; the step reads the task (its draft, the specification described, the citations, the history) and `GET /v1/rulebook/review/stats`, and the public listener answers the queue 404 in header mode. Nothing is edited, decided, approved or published, so the shared database's seed drafts stay drafts that need review; `test_review_flow.py` edits, approves and publishes on memory stores |
| extraction | only while the product's gateway answers from its fake model (`CW_LLM_PROVIDER=fake`, the default), skipped otherwise: the check asks no real model. `GET /v1/pipeline/tasks?kind=triage` answers with triage tasks only; a triage resolution of a task id nobody opened is refused 404 `pipeline-task-not-found`, and a relevant one without a type 422 `request-invalid`, so no task changes. The rule extraction's stage, built as the worker builds it, asks the gateway on the internal listener with the registered prompt `extraction.rule_candidate@1` about a synthetic notification stored nowhere: the gateway takes the prompt (its digest is the registry's), and the fake model's placeholder cites no clause, so it is read as no candidate twice. Nothing is ingested, uploaded, stored or published; each ask leaves a row in the gateway's ledger. `test_extraction_flow.py` extracts from a recorded notification |

The fanout, changes and public steps read the business directory, the audit rows (of no tenant,
and the CA firm's bulk notifications) and the engine's row counts of a tenant, which no route
serves and no policy lets `cw_app` read across tenants.
`make product-check` gives them `CW_PRODUCT_RECORDS_URL`, the database owner's URL, and the tool
opens it read only (`default_transaction_read_only`), so the session can run nothing but
queries.

`ARGS="--json"` prints the result as JSON, `ARGS="--step loop"` runs one step, and
`ARGS="--destructive"` lets the rollback step withdraw gstr9_annual (CI only). A later package
appends its steps to `STEPS` in `tools/demo/src/cw_demo/product/check.py`.

## `make product` and `make web-stack`

`make web-stack` is the UI-only stack: ten separate service processes on 8001 to 8010, memory
stores unless `STORE=postgres`, and no worker, so nothing there turns a decision into
obligations or a message. `make product` is the full product. Both use `make dev`'s Postgres,
Kafka and Temporal, so with `make web-stack STORE=postgres` they share the database: the
product's worker relays and consumes what either writes, and runs the services' periodic jobs
there (the reminder sweep, the notification retention sweep, the purge of expired idempotency
keys). The web stack connects as the superuser and so reads across tenants; the product does not.

## Troubleshooting

- **A port is in use.** `make product` names it. `lsof -nP -iTCP:<port> -sTCP:LISTEN` shows who
  holds it. Move the web app with `WEB_PORT`, the worker's health with `PRODUCT_WORKER_PORT`, the
  listeners with `CW_MVP_PUBLIC_PORT` and `CW_MVP_INTERNAL_PORT` (and `CW_MVP_INTERNAL_URL`).
- **A process exited while starting.** `make product-wait` prints the end of its log;
  `make product-logs PROC=app FOLLOW=0` prints more. From the image, `make product-image` prints
  the containers' last lines when one does not come up, and
  `make product-image-logs PROC=release FOLLOW=0` (or `app`, `worker`) the rest. A release that
  stops at a migration names the service and alembic's error; one that stops at the topics names
  the broker.
- **`cw-product` is refused.** `CW_ENV` must be local or test and `CW_AUTH_MODE` header or dual,
  in the environment or `.env`.
- **The loop waits for obligations.** The worker's `/loops` must run
  `obligation/consumer:obligation.decisions` and the relays; `make dev-logs SERVICE=redpanda`
  shows the broker. A new consumer group reads from the earliest offset.
- **The recompute step waits for a decision.** The worker's `/loops` must run
  `applicability-engine/consumer:applicability-engine.profiles`; `make product-logs PROC=worker`
  shows `applicability.profile_recomputed` for each event with what it decided and published.
  `evaluated=False` there means `CW_APPLICABILITY_RECOMPUTE_ENABLED` is not on for the worker.
- **The fanout step waits for the run.** The worker's `/loops` must run
  `applicability-engine/consumer:applicability-engine.rules` and the `applicability` task queue,
  and `make product-logs PROC=worker` shows `applicability.rule_event` for the publication. A run
  that reads `disabled` means `CW_APPLICABILITY_FANOUT_ENABLED` was off for the worker when the
  version was published; the Temporal UI (http://localhost:8233) shows the workflow
  `applicability-fan-out-<rule version id>`.
- **The reminders step finds no reminder.** `make product-logs PROC=worker` shows
  `notification.event_queued` for the obligation.due_soon the sweep wrote, and the check's error
  names the sweep's exit code and report; `obligation-sweep: refused` means `CW_ENV` is not local
  or test, or the obligation store is not postgres.
- **The tracking step waits for an obligation.** It needs what the recompute step needs: the
  engine's consumer of profile.updated and obligation's consumer of applicability.decided. A 409
  `obligation-closed` or a history that reads otherwise means something else changed the
  probe's obligation; the step names what it read.
- **The changes step fails on the dry run's counts.** It counts the CA firm's registrations the
  business directory lists. A registration made before the engine's consumer group existed is not
  listed (the fanout step reports it "not in the directory"), so neither the fan-out nor a dry run
  reads it, though `cw-product seed` still evaluates it; the step leaves it out. Counts that still
  differ mean the profiles changed since the version was decided.
- **A late decision made nothing.** `obligation.decision_guarded` in the worker's log names the
  reason: `rule_withdrawn`, `rule_superseded` (with the periods) or `uncited`.
- **The loop waits for the change card.** `tail var/product/sink.jsonl` shows what the sink got;
  `GET /v1/notification/notifications?business_id=<registration id>` for the tenant shows each
  notification's state and error.
- **`role "cw_app" does not exist` or a permission error.** Run `make product-role`; it grants the
  tables later migrations created too.
- **`next-env.d.ts` imports `.next/product`.** Next rewrites that git-ignored file for the dev
  server that started last; either version works, and `make web-dev` writes its own back.
