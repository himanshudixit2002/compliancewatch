# Temporal worker

What to do when a service's Temporal worker is down, a task queue is backing up, or a workflow
failed. Workers are built on `py_common.temporal` (ADR-004); the pipeline's is
`python -m pipeline.worker` (`make worker SERVICE=pipeline` locally), task queue `pipeline`.

## How it works

- A worker connects to `CW_TEMPORAL_ADDRESS` in `CW_TEMPORAL_NAMESPACE` and polls one task
  queue for the workflows and activities it registered. Several worker processes can share a
  queue.
- Every activity is an `ActivityBase` subclass: `validate`, `run`, `record`, with its retry
  policy and timeouts on the class. Temporal retries a failed activity per that policy; the
  workflow only ever sees the final outcome.
- Workflow and activity spans go to Tempo when `CW_OTEL_ENDPOINT` is set; every log line in an
  activity carries `workflow_id`, `activity_id`, `attempt` and, with telemetry on, `trace_id`.

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
