# The local product

`make product` brings up the working product on this machine: ADR-013's one deployable
(`composition/mvp`, its app and worker processes) with Kafka and Temporal on, on the dev stack,
and the web app. `make product-seed` fills it with two synthetic tenants and a synthetic
publication of the seed rules the golden world cites, and `make product-check` proves that a
published rule becomes decisions, obligations with citations and a change card.

```bash
make product                 # make dev, make migrate, make product-role, the seed calendar, then
                             # cw-mvp serve, cw-mvp worker and next dev; waits until all answer
make product-seed            # synthetic tenants, the demo publication, the first decisions
make product-check           # health, honesty, loop, isolation: exit 0 means accepted
make product-logs PROC=worker   # app, worker or web; FOLLOW=0 prints the end and returns
make product-down            # stops only what make product started
```

`WEB=0` leaves the web app out (CI does), `WEB_PORT=3400` puts it on another port. Run
`make product` again at any time: it starts only what is not running. Everything it writes stays
in the dev database until `make dev-reset`.

## What runs

| Process | Where | What |
| --- | --- | --- |
| app | public listener `127.0.0.1:8000`, internal listener `127.0.0.1:8080` | `cw-mvp serve`: every service's API in one process ([composition/mvp/README.md](../../composition/mvp/README.md)). The internal listener serves every route; the web app and `cw-product` call it |
| worker | health `127.0.0.1:8081` (`/health`, `/loops`) | `cw-mvp worker` with `CW_WORKER_KAFKA_ENABLED` and `CW_WORKER_TEMPORAL_ENABLED` on: the outbox relay of every schema, obligation's consumer of applicability.decided (group `obligation.decisions`), notification's consumer of the obligation events (group `notification.obligations`), the notification dispatcher and retention sweep, obligation's reminder sweep, the rulebook's transition sweep and the pipeline's Temporal task queue |
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
`make web-stack`), the worker's two switches and the reminder sweep on, rule publishing on with
the placeholder tokens `local-write-token` and `local-review-token` (not secrets; values in
`.env` win), the profile's static GSTIN lookup, the notification sink in place of the real
channels with a five-second batching window, and message links to the product's web app.

## From a published rule to a change card

1. `cw-product publish` takes a seed rule from draft to published as synthetic analysts (below);
   `rule.published` goes to the rulebook's outbox.
2. `cw-product evaluate` asks the engine to decide every published rule for every seeded
   registration. Nothing else triggers the engine yet: a later package lets it consume
   profile.updated and rule.published. The decision and its applicability.decided event are
   stored together.
3. The worker's relay publishes the event; obligation's consumer materialises two periods of an
   applying rule (obligation.created each) and closes nothing for one that does not apply.
4. Notification's consumer queues one change card per rule version, business, recipient and
   channel (the second period's event is a duplicate), due after the five-second window.
5. The dispatcher (every five seconds) renders it. The synthetic owner hears on WhatsApp first and
   email second, has never written to the business number, and every template is a draft, so
   the WhatsApp attempt is refused exactly as the Cloud API adapter refuses it (outside the
   24-hour window, template not approved) and the email fallback goes at once.
6. The sink records both, `refused` and `sent`, in `var/product/sink.jsonl`.

The whole chain takes about ten seconds; `make product-logs PROC=worker` shows each step
(`obligation.decision_applied`, `notification.event_queued`, `notification.dispatched`).

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
| Demo CA Associates (synthetic), a CA firm | `00000000-0000-4000-8000-0000000d0002` | Demo Client One Bengaluru (synthetic), the demo GSTIN, quarterly; Demo Client Two Delhi (synthetic), the made-up 07ZZZZZ9999Z1Z5, quarterly | group A of the quarterly GSTR-3B; group B |

For each tenant the seed records the consents of its owner (or the firm's admin) through the API,
registers the GSTINs with the pre-fill and the answers, and registers a recipient with a phone
number (+91 followed by zeros, which no Indian mobile number starts with) and a mailbox on the
reserved `.invalid` domain, both opted in with no quiet hours of their own, so the loop completes
at any hour. The firm's admin hears by the daily digest (09:00 IST), as every CA firm's people do.

## Honesty

- Only the four seed rules `evals/golden/qa/kag/world.yaml` cites from recorded quotes can be
  published: gstr3b_monthly, gstr3b_quarterly_group_a, gstr3b_quarterly_group_b (the default)
  and gstr9_annual (`make product-seed ARGS="--rule gstr9_annual"`, or
  `cw-product publish --rule gstr9_annual`). The other nine stay drafts.
- The recorded CBIC notifications the world uses are registered through the rulebook's pipeline
  write route, and the rulebook verifies every quote against the stored clause.
- Each version is submitted by "Demo analyst (synthetic)", tagged high impact, approved by "Demo
  reviewer one (synthetic)" and "Demo reviewer two (synthetic)" with `synthetic: true`, and
  published; every note says "synthetic demo publication - not an analyst review". A synthetic
  approval leaves the version's seed status at needs_review, and the rulebook accepts one only
  where `CW_ENV` is local or test. Nothing is marked reviewed.
- `cw-product` refuses to run unless `CW_ENV` is local or test and `CW_AUTH_MODE` header or dual.
- A published version stays published: the rulebook has no way back for it short of withdrawing
  it, which ends it, and only `make dev-reset` gives a dev database without it.

## Signing in on the web

After `make product-seed`, open the sign-in page of the product's web app, choose "Use the last
seeded tenant" (it reads `var/seed/last.json`, which the seed writes in the shape the web seed
does), a role and a display name, and sign in: the business page of Demo Traders (synthetic)
opens. For the CA firm, choose the tenant kind CA firm and paste its id from the table above.
The obligations screen is not built yet; the obligations are in the API:

```bash
curl -s 'http://127.0.0.1:8080/v1/obligation/obligations?business_id=<registration id>' \
  -H 'x-tenant-id: 00000000-0000-4000-8000-0000000d0001'
```

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
| health | `/ready` on the internal listener lists every service's checks as ok, the public listener answers, and the worker's `/loops` runs both consumer groups, the outbox relays, the dispatcher, the reminder sweep and the `pipeline` task queue |
| honesty | every published seed rule is one the world cites and reads needs_review, every other seed rule is a draft, nothing is marked reviewed, and the golden world and its cases are drafts |
| loop | evaluates the business tenant, then waits for the decisions its answers call for, an obligation of each rule that applies whose version cites a verified clause, and a change card about the business sent through the sink (with its line in the sink file) |
| isolation | the CA firm reads none of the business tenant's decisions, obligations, notifications or business, and the other way round |

`ARGS="--json"` prints the result as JSON, `ARGS="--step loop"` runs one step. A later package
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
  `make product-logs PROC=app FOLLOW=0` prints more.
- **`cw-product` is refused.** `CW_ENV` must be local or test and `CW_AUTH_MODE` header or dual,
  in the environment or `.env`.
- **The loop waits for obligations.** The worker's `/loops` must run
  `obligation/consumer:obligation.decisions` and the relays; `make dev-logs SERVICE=redpanda`
  shows the broker. A new consumer group reads from the earliest offset.
- **The loop waits for the change card.** `tail var/product/sink.jsonl` shows what the sink got;
  `GET /v1/notification/notifications?business_id=<registration id>` for the tenant shows each
  notification's state and error.
- **`role "cw_app" does not exist` or a permission error.** Run `make product-role`; it grants the
  tables later migrations created too.
- **`next-env.d.ts` imports `.next/product`.** Next rewrites that git-ignored file for the dev
  server that started last; either version works, and `make web-dev` writes its own back.
