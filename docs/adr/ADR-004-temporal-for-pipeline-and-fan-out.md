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

## Addendum (2026-10-05): the rule.published fan-out as built

The fan-out the decision describes now runs, behind the flag `applicability.fanout`. What the
build settled that the decision left open:

- **One workflow per version, ever.** `FanOutWorkflow` (type `applicability.fan_out`) runs on the
  task queue `applicability` with the workflow id `applicability-fan-out-<rule version id>` and the
  id reuse policy `REJECT_DUPLICATE`: a redelivered `rule.published` cannot start a second run,
  finished or not. The engine's rules consumer starts it in the read phase of its inbox handler,
  with no transaction open, and records the run in `applicability.fanout_run` in the write phase;
  the workflow's first activity inserts the same row if it is absent, so neither order loses it.
- **The checkpoint is the batch.** A batch is 1,000 directory entries (`business_directory`, read
  across tenants), decided one tenant group at a time: the profiles are read over HTTP with no
  transaction open, then the group's decisions are written in one unit of work of the tenant.
  Decision ids derive from the `rule.published` event, the business and the version, so a retried
  batch stores nothing twice. After 100 batches, or when its history grows long while it waits, the
  workflow continues as new, carrying the cursor and the counters.
- **The row decides, signals wake.** The global hold (`fanout_hold`) and the run's row are read at
  every batch boundary. The controls (pause, resume, cancel, hold, release) change the row and write
  their audit entry in one transaction, and only then signal the workflow, so a lost signal costs
  one poll (30 seconds) and never a wrong state. A cancel signal is final on its own.
- **The run pauses itself on flips.** Once 200 businesses have been compared with the version it
  supersedes, a flip rate above 2% pauses the run, audited as the system; a person resumes it (the
  check is then off for the run) or cancels it and withdraws the version.
- **Activities are idempotent and retried by kind.** The database steps retry until the database
  answers; a batch retries for about 40 minutes with backoff and then fails the run, except when the
  version is no longer published, which no retry fixes.
- **No time-skipping server in tests.** The workflow is tested on `WorkflowEnvironment.start_local`
  (the time-skipping server needs Rosetta on Apple Silicon), and its control loop runs in-process
  too, so the journey tests drive it without Temporal.

Not built yet: the coarse filter over indexed profile attributes and the load test of 100,000
businesses in an hour (both with the fan-out at scale), and the flip-rate alert.
