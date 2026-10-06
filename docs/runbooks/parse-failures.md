# Parse failures (ParseFailureQueueHigh)

The pipeline parses every document it stores through its parser chain
(`services/pipeline/README.md`, "The parser chain"): the PDF's text layer, the table-aware PDF
parser, the HTML parser and the table-aware HTML parser. A document no parser reads (a scanned
PDF with no text layer, a file no parser opens, a media type none takes) does not fail its
ingest: the ingest sets the document `failed`, opens a **manual-parse task** for it and stops
there, so nothing of it is registered in the rulebook and no rule can cite it until an analyst
transcribes it.

`ParseFailureQueueHigh` raises a ticket for Regulatory Intelligence when more than 20
manual-parse tasks have been open for 30 minutes. A few open tasks are normal work. A queue that
large means scans arrive faster than they are transcribed, or a regulator site has started to
publish documents the parsers cannot read (scans in place of text, a new file type). Until each
is transcribed, a notification it holds reaches no customer.

The pipeline's app reports `pipeline_open_tasks{kind}` while `CW_OTEL_ENDPOINT` is set: the open
tasks of each kind (`manual_parse`, `triage`), zero for a kind with none. It comes from one
reading of the `pipeline_task` table at most every 30 seconds; a failed reading logs
`task_metrics.read_failed` and reports nothing, so a database the app cannot reach shows as
missing data, not as an empty queue.

## Triage

1. How many, and since when: `GET /v1/pipeline/tasks?status=open&kind=manual_parse` on the
   internal listener (in token mode with an analyst's, reviewer's or admin's access token). The
   tasks come oldest first, each with its document (source, title, reference, URL) and `reason`:
   every parser's own reason, such as `pdf@1: UnparsedDocumentError: the PDF has no text layer`.
2. One source or many: group the open tasks by `source_key`. Many tasks from one source since a
   date point at that site; the reasons say whether its files lost their text layer, are a type
   no parser takes, or do not open at all.
3. The document itself: `GET /v1/pipeline/documents/{document_id}/raw` serves the stored bytes as
   they were fetched or uploaded. Open it: a page image with no selectable text is a scan.
4. The ingest: the Temporal UI lists the workflow (`pipeline-ingest-<source>-<url digest>` for a
   crawled document, `pipeline-upload-<source>-<id>` for an upload) with
   `pipeline.parse_document` failed and `pipeline.open_manual_parse` after it; the worker logs
   `pipeline.manual_parse_opened`.

## Fix

- **Transcribe the document.** `POST /v1/pipeline/tasks/{task_id}/resolve` (an admin, a reason)
  with the document typed by hand as a transcript: headings, numbered paragraphs and tables in
  document order, in the JSON shape the README gives. The route checks it first and names each
  problem by its place. The transcript is kept in the raw store, the task is resolved and
  audited, and an ingest starts (`pipeline-manual-parse-<task>`) that parses the document from
  it as `manual@1` and, while `CW_PIPELINE_KNOWLEDGE_ENABLED` is on, registers it. From then on
  the document is always parsed from its transcript. If the ingest could not start (a 503), the
  task stays resolved: send the same request again to start it.
- **Dismiss what needs no work.** `POST /v1/pipeline/tasks/{task_id}/dismiss` with the reason: a
  duplicate scan of a document already parsed, a user manual or a form that is not a regulatory
  document. The document stays `failed` and is never registered.
- **A better copy.** When the regulator publishes a text copy of the same document, upload it to
  the source (`POST /v1/pipeline/sources/{key}/uploads`) instead of transcribing the scan; dismiss
  the scan's task with the new document's id in the reason.
- **A site that changed.** When one source's documents all fail since a date, raise it with the
  Regulatory Intelligence lead: OCR is not built (it is planned behind its own flag), so until
  then the documents are transcribed or a text copy is uploaded. Never work around a site that
  blocks the crawler; pause the source instead (`docs/runbooks/source-stale.md`).

A parse that later succeeds (a parser added to the chain reads the document) closes its open
manual-parse task itself, with no person named in `resolved_by`.

## Escalation

The alert opens a ticket, not a page: the documents are stored and nothing is lost. If the queue
keeps growing for a working day, or a notification waiting in it changes a deadline that falls
within the week, the Regulatory Intelligence lead decides who transcribes first; deadline changes
go first.
