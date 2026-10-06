# Triage tasks (TriageQueueStale)

The pipeline classifies every document it parses before anything is registered
(`services/pipeline/README.md`, "Classification and triage"). A document whose opening names
another type than its source publishes (a circular among the notifications, a notification among
the press releases) is a **conflict**: the classify step sets the document `triage`, opens a
**triage task** with the classifier's reason, and the ingest stops there. Nothing of the document
is registered in the rulebook, and no rule candidate is extracted from it, until an analyst
decides what it is.

`TriageQueueStale` raises a ticket for Regulatory Intelligence when the oldest open triage task
has waited more than 24 hours, for an hour. A task or two a day is normal work. One that waits a
day means nobody is looking at the queue, or the queue grows faster than it is worked; a
notification waiting in it reaches no customer.

The pipeline's app reports `pipeline_task_oldest_open_age_seconds{kind}` while `CW_OTEL_ENDPOINT`
is set: how long the oldest open task of each kind (`manual_parse`, `triage`) has waited, zero for
a kind with none, beside `pipeline_open_tasks{kind}`, how many are open. Both come from one
reading of the `pipeline_task` table at most every 30 seconds; a failed reading logs
`task_metrics.read_failed` and reports nothing, so a database the app cannot reach shows as
missing data, not as an empty queue.

## Triage

1. How many, and since when: `GET /v1/pipeline/tasks?status=open&kind=triage` on the internal
   listener (in token mode with an analyst's, reviewer's or admin's access token). The tasks come
   oldest first, each with its document (source, title, reference, URL) and `reason`, the
   classifier's, such as "its opening names it a circular, but its source publishes the type
   notification".
2. One source or many: group the open tasks by `source_key`. Many from one source since a date
   point at a site that changed what it lists, or at a heading the detector misreads (a false
   conflict). With the crawl on, GSTN advisories that name a notification are a known case.
3. The document itself: `GET /v1/pipeline/documents/{document_id}/raw` serves the stored bytes.
   Read its opening: the type it names, and whether it is a regulator's document at all.
4. The classification: the task's document is `triage`; the `document.classified` event of the
   conflict carries the type read, the confidence `conflict` and the reasons.

## Fix

- **Decide.** `POST /v1/pipeline/tasks/{task_id}/resolve` (an admin, a reason) with `triage`:
  `{"relevance": "relevant", "doc_type": "circular"}`, the type the document is, or
  `{"relevance": "irrelevant"}` for no regulatory document. The decision becomes the document's
  classification (`certain`, by `triage`, the analyst in `decided_by`), audited as
  `pipeline.task.resolve`. A relevant document continues through an ingest
  (`pipeline-triage-<task>`) that registers it as the decided type while
  `CW_PIPELINE_KNOWLEDGE_ENABLED` is on and extracts its rule candidate while
  `CW_PIPELINE_EXTRACTION_ENABLED` is on; an irrelevant one is set aside. The same decision again
  replays and starts the ingest if it did not start (send it again after a 503); another decision
  is a 409.
- **Dismiss only what needs no decision.** `POST /v1/pipeline/tasks/{task_id}/dismiss` with the
  reason, such as a duplicate of a document decided already. The document stays `triage` and
  unregistered, and nothing reopens it: a route to classify a document again is not built yet.
- **A detector that misreads a source.** When one source's documents keep landing in triage for
  the same reason, raise it with the Regulatory Intelligence lead: the detector
  (`services/pipeline/src/pipeline/application/detector.py`) reads the opening of each document
  for the words regulators use, and a change there is a code change with its tests. Decide each
  waiting task meanwhile.

## Escalation

The alert opens a ticket, not a page: the documents are stored and nothing is lost. If the queue
keeps growing for a working day, or a notification waiting in it changes a deadline that falls
within the week, the Regulatory Intelligence lead decides who triages first; deadline changes go
first.
