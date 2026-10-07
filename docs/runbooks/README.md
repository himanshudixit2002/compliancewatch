# runbooks

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, section 18.

- **Owns:** One runbook per alert, linked from the alert itself (a runbook without a link fails CI)
- **Owning team:** Platform and Infrastructure (each service owner writes the runbooks for their alerts) (guide section 14)
- **Consumes:** n/a
- **Emits / publishes:** n/a

## Layout

Flat; one markdown file per alert or operational procedure.

- [api-slo-burn.md](api-slo-burn.md): the availability and latency SLO alerts on the product APIs.
- [audit-export.md](audit-export.md): what the audit trail holds, who reads which rows (`GET /v1/identity/audit`), exporting a month with `identity-admin audit-export` and uploading it to the object-locked bucket.
- [backup-restore.md](backup-restore.md): what holds state, dev backups, the quarterly restore drill.
- [data-requests.md](data-requests.md): a tenant's export or deletion request past its 30-day deadline (DataRequestOverdue), the open and overdue gauges, the directory role and function that count them, a service that does not answer its part of an export.
- [entity-review-queue.md](entity-review-queue.md): mentions waiting too long or piling up in the rulebook's entity review queue (EntityReviewQueueStale, EntityReviewQueueBacklog).
- [fan-out-control.md](fan-out-control.md): the rule.published fan-out over every business: the global hold, pausing, resuming and cancelling a run, a run that paused itself on flips, one that stays held, paused or failed, a publication with no run, and rolling a version back.
- [notification-delivery.md](notification-delivery.md): notifications that fail for good, are delivered twice or wait past the 15-minute objective, and email bounces and complaints (NotificationDeliveryFailures, NotificationDuplicateSent, NotificationPendingOverdue, NotificationEmailBounces), the delivery metrics and receipts, the SES feedback subscription, and where a failure's cause shows.
- [outbox-relay.md](outbox-relay.md): events not reaching Kafka, `dead` outbox rows (OutboxDeadLetters, OutboxBacklog), requeueing a dead row (the pipeline's `POST /v1/pipeline/outbox/{event_id}/requeue`), a message a consumer dead-lettered and `make replay`, pruning.
- [pipeline-backfill.md](pipeline-backfill.md): filling the pipeline's store with a regulator's history through the crawl workflow from a plan: the dry run, the backfill, the report, and what follows.
- [parse-failures.md](parse-failures.md): documents no parser reads waiting for a manual parse (ParseFailureQueueHigh), the open-tasks gauge, transcribing a document, dismissing a task, a site whose documents stopped parsing.
- [pipeline-triage.md](pipeline-triage.md): documents held for an analyst's triage too long (TriageQueueStale), the oldest-task gauge, deciding or dismissing a triage task, a source the detector misreads.
- [rule-review-queue.md](rule-review-queue.md): rule versions waiting too long for an analyst's decision as review tasks (RuleReviewQueueStale), the queue gauges and stats, claiming, editing and deciding a task, a high-impact version waiting for its second reviewer, a seed backlog.
- [rulebook-data-quality.md](rulebook-data-quality.md): the nightly data-quality checks over rule versions, citations and relations, what each violation means, and the read-only role for a deployed database.
- [source-stale.md](source-stale.md): a regulator source no crawl has listed for more than two cadences (SourceStale), the freshness gauges, why a crawl fails or never starts, pausing a source a site blocks.
- [secret-rotation.md](secret-rotation.md): every deployed secret with its holders, owner and cadence, and how to rotate each without an outage: identity's signing keys, service client secrets, the shared tokens, Supabase keys, database passwords and provider keys.
- [temporal-worker.md](temporal-worker.md): a task queue with no worker (TemporalWorkerDown), no spans reaching the collector (TelemetrySilent), a worker that will not start, a task queue backing up, a failed workflow.
- [whatsapp.md](whatsapp.md): the Meta manual steps, consent recording and its flag, webhook signature failures, opt-outs that must be honoured, late or failed reminders, delivery statuses the bot forwards and the 24-hour window, template rejections.

## Alerts

`infra/dev/prometheus/alerts.yml` holds the paging rules; each carries a `runbook_url` into this
directory and `make runbooks-check` (part of `make check`) fails when a link is missing or dead.
`make alerts-check` (the ops job in CI) runs promtool over the rules and their unit tests in
`infra/dev/prometheus/alerts.test.yml`, which pin when `ApiErrorBurnRate`,
`ApiLatencyBurnRate`, `TemporalWorkerDown` and `TelemetrySilent` fire; a new alert group, or a
change to a tested rule, comes with its cases there. A `runbook_url` may name a section of its
runbook (`temporal-worker.md#temporalworkerdown`), and the check then also requires a heading
with that anchor.
Wired now: `ApiErrorBurnRate`, `ApiLatencyBurnRate`, `OutboxDeadLetters`, `OutboxBacklog`,
`TemporalWorkerDown`, `TelemetrySilent`, `EntityReviewQueueStale`, `EntityReviewQueueBacklog`,
`NotificationDeliveryFailures`, `NotificationDuplicateSent`, `NotificationPendingOverdue`,
`NotificationEmailBounces`, `SourceStale`, `ParseFailureQueueHigh`, `TriageQueueStale`,
`RuleReviewQueueStale`.
Pending their metrics: decision-flip rate after a deploy (the fan-out already pauses
itself on flips, [fan-out-control.md](fan-out-control.md)), LLM spend past 80% of the monthly
budget before the 20th.
