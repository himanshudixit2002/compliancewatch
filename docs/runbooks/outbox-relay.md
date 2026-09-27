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
