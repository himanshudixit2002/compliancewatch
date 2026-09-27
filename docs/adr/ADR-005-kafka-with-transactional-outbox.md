# ADR-005: Kafka with a transactional outbox for all domain events

- **Status:** Accepted
- **Date:** 2026-09-27
- **Deciders:** Platform and Infrastructure, with every producing and consuming team

## Context

Services react to each other only through events: rule.published starts the fan-out,
applicability.decided creates obligations, obligation.created triggers notifications. Two
failure modes are unacceptable. A lost event means a business never hears about a rule; a
phantom event means a notification about a change whose transaction rolled back. Consumers must
also be able to replay after a bug fix, and each service must read in order within its own
consumer group. Publishing straight from the service after commit has the dual-write problem:
commit then crash loses the event, publish then roll back invents one. RabbitMQ was considered
and set aside because it keeps no log to replay from; SQS because it gives no ordering across
services and no fan-out to several consumer groups without extra pieces.

## Decision

Kafka (Amazon MSK; Redpanda locally) carries every domain event. Producers write the event into
an outbox table in the same database transaction as the state change, and a relay publishes
from the outbox to Kafka. Topics are named object.verb in the past tense; payloads are versioned
JSON with a schema in `packages/contracts`; every event carries event_id, occurred_at,
tenant_id (null for regulatory events), correlation_id and causation_id. Consumers are
idempotent on event_id, each has a dead-letter topic, and the admin console can replay a
dead-lettered event after a fix.

## Consequences

- No lost and no phantom events: an event exists exactly when its transaction committed.
- Replay is a consumer-group offset reset, and a new consumer can rebuild its state from the log.
- Delivery is at least once, so every consumer must be idempotent; the notification dedupe key is
  the last line of defence against a duplicate message to a business.
- The relay is one more moving part (it lives in py-common), it adds a little latency, and the
  outbox table needs pruning.
- Schema compatibility must be checked in CI so a producer change cannot break a consumer; that
  check is still to be wired.
- Revisit only if event volume stays so low that a Postgres-backed queue would be simpler; the
  fan-out volume is the reason to expect it will not.
