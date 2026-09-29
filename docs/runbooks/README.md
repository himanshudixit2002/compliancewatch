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
- [notification-delivery.md](notification-delivery.md): notifications that fail for good or are delivered twice, and email bounces and complaints (NotificationDeliveryFailures, NotificationDuplicateSent, NotificationEmailBounces), the delivery metrics and receipts, the SES feedback subscription, and where a failure's cause shows.
- [outbox-relay.md](outbox-relay.md): events not reaching Kafka, `dead` outbox rows (OutboxDeadLetters, OutboxBacklog), replay by hand, pruning.
- [rulebook-data-quality.md](rulebook-data-quality.md): the nightly data-quality checks over rule versions, citations and relations, what each violation means, and the read-only role for a deployed database.
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
`NotificationDeliveryFailures`, `NotificationDuplicateSent`, `NotificationEmailBounces`.
Pending their metrics: source
freshness (two missed cadences), decision-flip rate after a deploy, LLM spend past 80% of the
monthly budget before the 20th.
