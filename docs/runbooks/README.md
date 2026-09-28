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
- [outbox-relay.md](outbox-relay.md): events not reaching Kafka, `dead` outbox rows (OutboxDeadLetters, OutboxBacklog), replay by hand, pruning.
- [temporal-worker.md](temporal-worker.md): a worker that will not start, a task queue backing up, a failed workflow.
- [whatsapp.md](whatsapp.md): the Meta manual steps, webhook signature failures, opt-outs that must be honoured, late or failed reminders, template rejections.

## Alerts

`infra/dev/prometheus/alerts.yml` holds the paging rules; each carries a `runbook_url` into this
directory and `make runbooks-check` (part of `make check`) fails when a link is missing or dead.
Wired now: `ApiErrorBurnRate`, `ApiLatencyBurnRate`, `OutboxDeadLetters`, `OutboxBacklog`,
`PipelineWorkerSilent`. Pending their metrics: source freshness (two missed cadences),
decision-flip rate after a deploy, notification failure rate and duplicates, LLM spend past
80% of the monthly budget before the 20th.
