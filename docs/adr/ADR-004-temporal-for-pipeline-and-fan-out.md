# ADR-004: Temporal for pipeline and fan-out orchestration

- **Status:** Accepted
- **Date:** 2026-09-27
- **Deciders:** Platform and Infrastructure, Regulatory Intelligence, Core Product

## Context

Two kinds of work run for a long time and must survive failure. The regulatory pipeline (crawl,
detect, parse, extract, review) has stages that take minutes, call unreliable external systems
(regulator sites, OCR, model providers) and must never lose a document. The fan-out re-evaluates
one published change for up to 100,000 businesses within an hour and has to be idempotent and
resumable after a deploy or a crash. Both need retries with backoff, timers (source cadence
alerts, quiet hours), a view of where each run stands, and resumption from the last completed
step. Celery was considered: a task queue with no durable workflow state, so multi-step
orchestration and resumption would be hand-written. Airflow was considered: batch scheduling of
DAGs, a poor fit for event-driven per-document work and per-business fan-out. Serverless
workflows were ruled out for the pipeline because of cold starts, vendor lock and harder local
debugging.

## Decision

Temporal, self-hosted on Kubernetes with Postgres persistence. Every pipeline stage is an
activity inside a per-document workflow; the fan-out is a workflow with a checkpoint every
1,000 businesses. Retries, timeouts and heartbeats are declared on the activity, not coded in
it. Workers run on the workers node pool; the local stack runs Temporal in Docker Compose with
its UI on port 8233.

## Consequences

- Retries, timeouts and resumption are declarative; a crashed worker picks up from the last
  completed activity, and a source that goes silent is a timer, not a cron job.
- The Temporal UI shows where every document and every fan-out is, which is the pipeline's main
  operational view.
- Workflow code must be deterministic (no I/O, no clock or random reads, versioned changes).
  This is a learning curve; all side effects live in activities.
- One more stateful system to run and upgrade, owned by Platform.
- Workflows do not replace domain events. A stage still records its event through the outbox
  (ADR-005) so other services can react without knowing about Temporal.
- Revisit if self-hosting costs more than Temporal Cloud would, or if the work turns out to be
  short and stateless enough that a plain queue would do.
