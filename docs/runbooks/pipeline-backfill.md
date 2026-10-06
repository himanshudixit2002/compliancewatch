# Pipeline backfill

Filling the pipeline's store with a regulator's history through the crawl workflow, from a plan,
and reading where the documents got to. No alert pages for it: a person runs it, on purpose,
because **it reads the live regulator sites**. No test, check or CI job runs it against a live
site; the tests crawl recorded fixtures only.

The command is `pipeline-backfill` (`services/pipeline/src/pipeline/backfill.py`); `make backfill`
runs it on the local database's `pipeline` schema (the one `make migrate` uses, credentials from
`.env`). The plan is `services/pipeline/backfill-plan.yaml`: first the notifications the seed
rules cite, each in the window of the year its number names, then about 200 recent
notifications. The CGST Rules the seed calendar also cites are upload-only (`cgst_rules`):
upload them, nothing crawls them. The pipeline README's
[Operations](../../services/pipeline/README.md#operations) section describes the modes.

## Before

- The pipeline schema is migrated: `make migrate SERVICE=pipeline` (migration 0005 adds the
  crawl runs' trigger).
- A pipeline worker runs on the dev stack's Temporal (task queue `pipeline`): the dev stack's,
  or `make worker SERVICE=pipeline` in another shell. It does the fetching. It needs no crawl
  flag for a backfill; with `CW_PIPELINE_CRAWL_ENABLED=true` it would also start its tick, which
  crawls every source at its cadence. What its ingests do follows its own flags: they register
  the documents in the rulebook while `CW_PIPELINE_KNOWLEDGE_ENABLED` is on, and extract rule
  candidates while `CW_PIPELINE_EXTRACTION_ENABLED` is on (a backlog left with it off is swept
  later with `make extract-backlog`).
- Nobody else crawls the same source meanwhile: a row whose source has a crawl running stops
  with `CrawlRunningError` and says so.

## 1. Dry run

```bash
make backfill ARGS="--plan services/pipeline/backfill-plan.yaml --dry-run"
```

For each row it lists the row's window through the source's adapter (the polite client: the
crawler user agent, `robots.txt`, a second between requests to a host) and counts what the
listing holds: listed, already stored (by URL), new. It fetches no document and writes nothing.
`--row 2` runs one row, `--json` prints JSON. Exit 1 when a row's listing failed (the line says
why: the site, its token API, a layout change), 2 when the store cannot be read.

Read it before going on: a cited notification missing from its row's listing is a wrong
reference or year in the plan, or a listing the adapter misreads; a row of hundreds of new
documents takes as many fetches.

## 2. The backfill

```bash
CW_PIPELINE_CRAWL_ENABLED=true make backfill ARGS="--plan services/pipeline/backfill-plan.yaml --workflow --reason 'Backfill the notifications the seed rules cite'"
```

The flag is the command's own consent to reach the live sites (it refuses without it, and without
a reason of ten characters or more). Each row's crawl is a crawl run with the trigger `backfill`,
under `pipeline-crawl-<key>-backfill-<request>`, and its `pipeline.source.backfill` row in
`audit.event` naming the system's backfill, or the person `--actor-id <uuid>` names, with the
reason. The command waits for each crawl and prints a line per crawl (listed, stored,
duplicates, failed, left for later), crawls the row again while documents were left for a later
crawl, and ends each row once nothing new is left, the last crawl kept nothing, the row's
`max_documents` were stored, or after `--max-rounds` (20) crawls; then a table of the rows. Exit
1 when a row's crawl failed or could not start.

A backfill is none of the source's crawls: each one records its run and leaves the source as it
found it. Its watermark stays where the schedule's crawls left it (a source the schedule never
crawled keeps none), and so do its last listing (its freshness, which the `SourceStale` alert
reads), its last error and its status, so the schedule's crawls go on from where they were. While
a backfill's crawl runs the tick starts no crawl of that source; once it ends, the schedule's next
crawl is due a cadence after the schedule's last one, not after the backfill. Interrupting the
command stops it waiting, not the crawl it started: that one ends on the worker and is recorded;
run the command again (with `--row N` from the row it stopped at) and what is stored already is
known and skipped.

Watching it: `GET /v1/pipeline/runs?trigger=backfill` on the internal listener (the runs, the
latest first, with their counts and errors), the Temporal UI for the workflows, and
`GET /v1/pipeline/documents?source_key=cbic_notifications` for the documents with their status.

## 3. The report

```bash
make backfill ARGS="--plan services/pipeline/backfill-plan.yaml --report"
```

Per source of the plan, from the store: stored, parsed, unparsed (no parser read it: each waits
for a manual parse, [parse-failures.md](parse-failures.md)), set aside as irrelevant, waiting
as classified, held for triage ([pipeline-triage.md](pipeline-triage.md)), kept for reference
and extracted, with the current prompt's candidates and unparseable answers; the share of
unparsed documents (more than 5% is the case for OCR); and how analysts decided the candidates,
from the rulebook's `GET /v1/rulebook/review/stats` at `CW_RULEBOOK_URL`
(`http://localhost:8003` by default; the local product's rulebook is on its internal listener,
`CW_RULEBOOK_URL=http://127.0.0.1:8080`). When the rulebook does not answer, or refuses (in
`token` mode the read wants an analyst's token), the report says the acceptance is unavailable
and why. `--json` prints JSON. It writes nothing.

## Afterwards

- Documents waiting as `classified` with the extraction off: `make extract-backlog
  ARGS="--dry-run"` counts them, and without `--dry-run`, once the flag is on, sweeps them.
- A document the detector set aside or misread: retry it with a type
  (`POST /v1/pipeline/documents/{document_id}/retry` with `stage` and `doc_type`, an admin's
  reason and an `Idempotency-Key`), which is audited.
- Rows that failed: read the run's error (`GET /v1/pipeline/runs?trigger=backfill&status=failed`;
  a backfill leaves the source's `last_error` to the schedule's crawls); a site that blocks the
  crawler is in [source-stale.md](source-stale.md).
- The crawl report (`make crawl-report`) leaves the backfill out: its runs, and the documents
  fetched while one ran, count in no total, close no gap and take no part in the detection
  delay.

`--legacy` keeps the command this one replaced, which fetches into a local raw store (`var/raw`)
outside the pipeline's store and records nothing: for recording fixtures only.
