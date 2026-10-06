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
- [backup-restore.md](backup-restore.md): what holds state, dev backups, the quarterly restore drill.
- [entity-review-queue.md](entity-review-queue.md): mentions waiting too long or piling up in the rulebook's entity review queue (EntityReviewQueueStale, EntityReviewQueueBacklog).
- [fan-out-control.md](fan-out-control.md): the rule.published fan-out over every business: the global hold, pausing, resuming and cancelling a run, a run that paused itself on flips, one that stays held, paused or failed, a publication with no run, and rolling a version back.
- [notification-delivery.md](notification-delivery.md): notifications that fail for good, are delivered twice or wait past the 15-minute objective, and email bounces and complaints (NotificationDeliveryFailures, NotificationDuplicateSent, NotificationPendingOverdue, NotificationEmailBounces), the delivery metrics and receipts, the SES feedback subscription, and where a failure's cause shows.
- [outbox-relay.md](outbox-relay.md): events not reaching Kafka, `dead` outbox rows (OutboxDeadLetters, OutboxBacklog), replay by hand, pruning.
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
`NotificationEmailBounces`, `SourceStale`.
Pending their metrics: decision-flip rate after a deploy (the fan-out already pauses
itself on flips, [fan-out-control.md](fan-out-control.md)), LLM spend past 80% of the monthly
budget before the 20th.
