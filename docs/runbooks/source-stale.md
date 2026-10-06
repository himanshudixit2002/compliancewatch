# Source stale (SourceStale)

The pipeline crawls each regulator source at its cadence (`services/pipeline/README.md`, "The
crawl"). `SourceStale` pages Regulatory Intelligence when no crawl has listed a source for more
than two cadences, for five minutes: a CBIC notifications source with a 2-hour cadence pages once
it has gone more than 4 hours without a successful listing (guide section 21: freshness alerts
page within two cadences). Until it is listed again, a notification the regulator publishes there
is not detected, and the F1 target (every new CBIC notification detected within 6 hours) slips.

The pipeline's app reports two gauges per enabled, unpaused source while
`CW_PIPELINE_CRAWL_ENABLED` is on and `CW_OTEL_ENDPOINT` is set:

- `pipeline_source_freshness_seconds{source}`: seconds since a crawl last listed the source, or
  since the source was added when none has;
- `pipeline_source_cadence_seconds{source}`: its cadence.

They come from one reading of the `source` table at most every 30 seconds. A failed reading logs
`source_metrics.read_failed` and reports nothing, so an app that cannot reach its database shows
as missing data rather than as a stale source. A paused or disabled source reports nothing and
never pages.

## Triage

1. Which sources: Prometheus or Grafana Explore, `max by (source)
   (pipeline_source_freshness_seconds) / max by (source) (pipeline_source_cadence_seconds)`. One
   source stale points at that site; every source stale points at the crawl itself (the worker,
   Temporal, the database).
2. How the source stands: `GET /v1/pipeline/sources` on the internal listener (in token mode
   with an analyst's, reviewer's or admin's access token). `status` is `failing` with
   `last_error` when crawls run and fail, `fetching` when one runs now, `healthy` with an old
   `last_fetch_at` when no crawl starts at all. `latest_run` has the last run's counts and error.
3. Is the tick running: the worker's `/loops` must list `pipeline/pipeline-crawl-tick` (with
   the crawl flag on) and the `pipeline` task queue; `worker.job_failed` with
   `job=pipeline-crawl-tick` or `pipeline.crawl_schedule_failed` in the worker's log says why a
   tick started nothing. A source whose run stays `running` is skipped until the run is three
   hours old, when the next tick closes it as abandoned and starts a new one.
4. What the crawl met: the Temporal UI shows the workflows `pipeline-crawl-<source>-<slot>` (and
   `-manual-<id>` for an admin's fetch) with their activities: `pipeline.list_new_documents`
   failing is the site (5xx, timeouts, `DisallowedByRobotsError`), a child
   `pipeline.ingest_document` failing is one document. `pipeline-crawl-report --days 1`
   (`make crawl-report ARGS="--days 1"` locally) gives the runs, failures and the longest gap per
   source.
5. Did the site change: a listing that answers but lists nothing new for days, or an adapter
   error such as a missing field, means the site's pages or API moved. Compare the live listing
   with the recorded one under `services/pipeline/tests/fixtures`.

## Fix

- A site that is down or slow: nothing to do but wait; the tick tries again every cadence and the
  alert resolves on the first successful listing. Start one at once with
  `POST /v1/pipeline/sources/{key}/fetch` (an admin, a reason) once the site answers.
- A site that refuses the crawler (robots.txt now disallows the path, a CAPTCHA, a block): never
  work around it. Pause the source (`PATCH /v1/pipeline/sources/{key}` with `paused: true` and a
  reason), which stops the alert, and raise it with the Regulatory Intelligence lead; documents
  are then added by hand until the site is readable again.
- A site whose pages or API changed: the adapter needs a fix and new recorded fixtures (the
  fixtures README lists how each was recorded). Pause the source until the fix is deployed.
- A worker that does not run the tick: check `CW_PIPELINE_CRAWL_ENABLED` and
  `CW_WORKER_TEMPORAL_ENABLED` on the worker, and the `TemporalWorkerDown` runbook
  ([temporal-worker.md](temporal-worker.md)).
- A source failing on one document (`last_error` names it) still lists, so it does not go stale;
  its watermark stays at that document's date so every crawl tries it again.

## Escalation

The alert pages: a stale CBIC source can hide a deadline change from every customer. If the
source is not listed again within one more cadence, the Regulatory Intelligence lead decides
whether analysts watch the site by hand meanwhile. A source paused because the site blocks the
crawler stays paused until the lead says otherwise; record the decision in the source's reason.
