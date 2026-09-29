# Temporal worker

What to do when a service's Temporal worker is down, a task queue is backing up, or a workflow
failed. Workers are built on `py_common.temporal` (ADR-004); the pipeline's is
`python -m pipeline.worker` (`make worker SERVICE=pipeline` locally), task queue `pipeline`.
Two alerts link here: [TemporalWorkerDown](#temporalworkerdown) and
[TelemetrySilent](#telemetrysilent).

## How it works

- A worker connects to `CW_TEMPORAL_ADDRESS` in `CW_TEMPORAL_NAMESPACE` and polls one task
  queue for the workflows and activities it registered. Several worker processes can share a
  queue.
- Every activity is an `ActivityBase` subclass: `validate`, `run`, `record`, with its retry
  policy and timeouts on the class. Temporal retries a failed activity per that policy; the
  workflow only ever sees the final outcome.
- Workflow and activity spans go to Tempo when `CW_OTEL_ENDPOINT` is set; every log line in an
  activity carries `workflow_id`, `activity_id`, `attempt` and, with telemetry on, `trace_id`.
- While a worker runs, its process reports `temporal_worker_up{task_queue} = 1`
  (`py_common.temporal.liveness`), exported with the other metrics when `CW_OTEL_ENDPOINT` is
  set. The series ends when the worker stops or fails, and the collector drops it from
  Prometheus 5 minutes later.

## TemporalWorkerDown

A task queue that reported `temporal_worker_up` in the last 6 hours has had no worker for 10
minutes after its series expired, so about 15 minutes after the last worker went away. The
alert names the queue in `task_queue`. Severity ticket; the team that owns the queue's service
answers it (`pipeline`: Regulatory Intelligence). Nothing is lost while it fires: Temporal keeps
the queue's tasks until a worker polls again, but ingestion and anything else the queue runs is
paused.

1. Is the worker process running? Look at the deployment's process list (locally, the terminal
   running `make worker`). Its last log lines say how it ended: `worker.stopped` is a clean stop
   (a deploy, a scale-down, SIGTERM), an error with a traceback is a crash. For a crash follow
   [The worker will not start](#the-worker-will-not-start), then start it again.
2. The process runs but the series is missing: the worker is not exporting metrics. Check its
   `CW_OTEL_ENDPOINT`, and whether [TelemetrySilent](#telemetrysilent) fires too, which points
   at the collector. Temporal itself says whether anything polls the queue:
   `docker compose exec temporal temporal task-queue describe --task-queue pipeline --address temporal:7233`
   lists the pollers, and the Temporal UI shows them on the queue's page.
3. The queue was retired on purpose (a renamed queue, a service removed): the alert stops by
   itself 6 hours after the last report; acknowledge the ticket until then.

Check locally: `make dev-observability`, then `CW_OTEL_ENDPOINT=http://localhost:4317 make worker
SERVICE=pipeline`; `temporal_worker_up` in Prometheus (http://localhost:9090) shows
`task_queue="pipeline"` = 1. Stop the worker and the series is gone about 5 minutes later.

## TelemetrySilent

Prometheus has no `otelcol_receiver_accepted_spans_total` for 30 minutes: the collector has not
received a span since it started, or Prometheus cannot scrape it. It says nothing about whether
workers run; [TemporalWorkerDown](#temporalworkerdown) does. Severity ticket, team Platform.

1. `up{job="otel-collector"}` in Prometheus. At 0 Prometheus cannot reach the collector: check
   the container (`docker compose ps otel-collector`) and its health endpoint (port 13133 in the
   container; `OTEL_HEALTH_PORT` on the host).
2. The collector is up: nothing exports to it. Every service and worker needs `CW_OTEL_ENDPOINT`
   (`http://localhost:4317` locally, the collector's address when deployed); an empty value
   turns telemetry off without an error. A restarted collector shows no counter until the first
   span arrives, so a quiet environment with no traffic can raise it too.
3. Spans arrive again once the exporters reach the collector; the alert resolves on the next
   evaluation.

## The worker will not start

1. `worker.started` missing from the log: read the error above it. `Connection refused` is the
   Temporal server (`make dev`, `docker compose ps temporal`); `namespace not found` means
   `CW_TEMPORAL_NAMESPACE` names a namespace the server does not have.
2. `duplicate activity names` or `must declare name`: two activity classes share a `name` or
   a class forgot its `name`, `input_type` or `output_type`; a code fix.

## A task queue is backing up

1. Temporal UI, http://localhost:8233 locally: the workflow list shows Running workflows with
   pending activities and how long they have waited.
2. No worker is polling the queue when the pending time keeps growing and the worker log shows
   nothing: start one. Workers are polling but slow when `activity.completed` lines show high
   `duration_ms`: look at the activity's trace in Tempo for the slow step, or raise
   `max_concurrent_activities` in the worker's `WorkerConfig`.

## A workflow failed

1. Open it in the Temporal UI: the failure carries the activity name, the attempt count and the
   exception. `activity.failed` log lines have the same `workflow_id`.
2. A non-retryable error (`InvariantViolationError`, `UnsupportedDocumentError`) means the
   input is wrong, not the environment; fix the input or the code, then start the workflow again
   with a new id. Temporal keeps the failed run for the history.
3. A retryable error that exhausted its attempts is usually an upstream outage; once it is
   over, reset the workflow from the UI ("Reset" to the last workflow task) or start it again.

## Local checks

- `make worker SERVICE=pipeline` in one terminal; in another, start `pipeline.ingest_document`
  with a small script that calls `py_common.temporal.connect` and
  `client.execute_workflow(IngestDocumentWorkflow.run, IngestRequest(...), id=..., task_queue="pipeline")`.
- `docker compose exec temporal temporal workflow list --address temporal:7233` lists recent runs.
