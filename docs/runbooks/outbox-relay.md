# Outbox relay

What to do when events are not reaching Kafka, or when a row in a service's `outbox_event` table
is marked `dead`. The relay is `py_common.outbox.relay` (ADR-005); one process runs per service
schema (`make relay SERVICE=<name>` locally).

## How it works

- A service writes each event into `outbox_event` in the same transaction as its state change,
  through `OutboxWriter`. The row starts as `pending`.
- The relay claims due `pending` rows with `FOR UPDATE SKIP LOCKED`, publishes each one to the
  Kafka topic named after the event (`obligation.created`), and marks it `published`. Several
  relay processes can share one table.
- A send that fails is retried after an exponential backoff (1 s, 2 s, 4 s ... capped at
  5 min); `attempts`, `available_at` and `last_error` show where a row stands.
- After 8 failed attempts the message is sent to `<topic>.dlq` and the row becomes `dead`. If
  even that send fails, the row stays `pending` and keeps backing off, so nothing is lost while
  the broker is down.
- Consumers keep their own dead-letter topics, `<topic>.<consumer group>.dlq`, for messages
  their handler could not process after three attempts; those messages were delivered correctly
  and the fix lives in the consumer.

## Alerts

With `CW_OTEL_ENDPOINT` set, the relay exports `outbox_relay_published_total`,
`outbox_relay_retried_total` and `outbox_relay_dead_total` by `topic`, and the gauge
`outbox_relay_pending` by `db_schema` (its `CW_DB_SCHEMA`, `unset` when empty): the pending rows,
counted at start and every 15 seconds.

- `OutboxDeadLetters` (page): a row of `topic` went dead in the last 30 minutes. See "A row is
  `dead`" below.
- `OutboxBacklog` (page): more than 1000 pending rows in `db_schema` for 15 minutes. See
  "Nothing is being published" below. The collector drops the series five minutes after the
  relay stops, so a relay that died shows as no data for its schema rather than as a backlog:
  check that the relay is running first.

## Nothing is being published

1. Is a relay running for that schema? `make relay SERVICE=<name>` locally; in a deployment, the
   relay is a separate process next to the service.
2. Can it reach the broker? The log line `outbox.publish_failed` carries the error; with the dev
   stack, `docker compose ps redpanda` and `make dev-urls`.
3. Is the table filling up? `select status, count(*) from <schema>.outbox_event group by 1`
   through `make dev-psql`. A growing `pending` count with rising `attempts` means the broker is
   the problem; a stable `pending` count with `attempts = 0` means no relay is running.

## A row is `dead`

The relay keeps when a row went dead in its `available_at` (it never claims a dead row), and the
same message sits on `<topic>.dlq`.

1. List the dead rows and read `last_error`. For the pipeline, `GET /v1/pipeline/outbox/dead`
   (internal listener; a regulatory role in token mode) lists them, the newest dead first, with the
   topic, key, attempts, last error, when each went dead and a summary of the payload without its
   body. For another schema: `select id, topic, attempts, available_at as dead_at, last_error from
   <schema>.outbox_event where status = 'dead' order by available_at desc` through
   `make dev-psql`. The copy on the dead-letter topic: `make replay ARGS="list --topic
   <topic>.dlq"`, which reads the topic with no consumer group and commits nothing.
2. Fix the cause (broker, topic configuration, message size).
3. Requeue the row, so the relay sends it again on its next pass and marks it `published`:
   - pipeline: `POST /v1/pipeline/outbox/{event_id}/requeue` with `{"actor_id": "<admin>",
     "reason": "<why, ten characters or more>"}` (an admin, or the shared write token in header
     mode). It moves only a dead row (back to `pending`, attempts reset, due now; `last_error`
     stays until a send succeeds), answers `requeued: false` for a row that is not dead, and
     writes its `pipeline.outbox.requeue` row to `audit.event` in the same transaction;
   - another schema, until it has a route: `update <schema>.outbox_event set status = 'pending',
     attempts = 0, available_at = now() where id = '<event id>' and status = 'dead'`.

   Consumers deduplicate on `event_id`, so a message that did get through before the row was
   marked dead is harmless.

Replaying the `<topic>.dlq` copy (`make replay ARGS="send --topic <topic>.dlq --event-id <id>"`)
publishes the same message too, but leaves the row `dead`: prefer the requeue, which keeps the
row the source of truth.

## A consumer dead-lettered a message

A consumer group sends what its handler could not process after three attempts to
`<topic>.<group>.dlq` and moves on (the headers say `origin_topic`, `consumer_group`, `attempts`
and `error`). The message was delivered; the fix lives in the consumer or what it reads.

1. List the topic: `make replay ARGS="list --topic <topic>.<group>.dlq"` (or `--json`): one line
   per message with its event id, origin, group, attempts and error. Listing is read only.
2. Fix the cause: the handler, the data it needs (the rulebook takes a rule candidate in only once
   its document is registered), the database it writes to.
3. Send the message back to its origin: `make replay ARGS="send --topic <topic>.<group>.dlq
   --event-id <id>"` (`--dry-run` says what it would send). It goes to the `origin_topic` header's
   topic (`--to` names another; a dead-letter topic is refused) with its key, value and headers
   less the dead-letter ones. Every group of the origin topic reads it again: the groups that took
   it in skip it (they deduplicate on the event id), and the one that failed runs its handler
   again. An event id the topic does not hold answers `holds no message with event id ...` and
   exits 1; a broker that does not answer exits 2.

## Ordering

Messages share a partition by `partition_key` (the tenant for tenant events, the aggregate the
producer chose otherwise). A row that is retried is published after rows that were written
later, so consumers must not rely on strict order across a broker outage; they reconcile from
the state the message describes, not from its position.

## Pruning

`published` rows are kept for auditing. Prune them on a schedule the service owner picks, for
example `delete from <schema>.outbox_event where status = 'published' and published_at <
now() - interval '30 days'`. `dead` rows are deleted only after they were requeued and published,
or written off.
