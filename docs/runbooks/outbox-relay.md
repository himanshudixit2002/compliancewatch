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

1. Read `last_error` on the row and the message on `<topic>.dlq`
   (`docker compose exec redpanda rpk topic consume <topic>.dlq -n 1`).
2. Fix the cause (broker, topic configuration, message size).
3. Replay by hand until the admin replay tool exists: set the row back to `pending`,
   `update <schema>.outbox_event set status = 'pending', attempts = 0, available_at = now()
   where id = '<event id>'`. The relay publishes it on its next pass. Consumers deduplicate on
   `event_id`, so a message that did get through before the row was marked dead is harmless.

## Ordering

Messages share a partition by `partition_key` (the tenant for tenant events, the aggregate the
producer chose otherwise). A row that is retried is published after rows that were written
later, so consumers must not rely on strict order across a broker outage; they reconcile from
the state the message describes, not from its position.

## Pruning

`published` rows are kept for auditing. Prune them on a schedule the service owner picks, for
example `delete from <schema>.outbox_event where status = 'published' and published_at <
now() - interval '30 days'`. `dead` rows are deleted only after they were replayed or written
off.
