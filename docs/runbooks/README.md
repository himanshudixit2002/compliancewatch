# runbooks

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, section 18.

- **Owns:** One runbook per alert, linked from the alert itself (a runbook without a link fails CI)
- **Owning team:** Platform and Infrastructure (each service owner writes the runbooks for their alerts) (guide section 14)
- **Consumes:** n/a
- **Emits / publishes:** n/a

## Layout

Flat; one markdown file per alert or operational procedure.

- [outbox-relay.md](outbox-relay.md): events not reaching Kafka, `dead` outbox rows, replay by hand, pruning.

## How to run

Nothing to run yet; the alerts that link these runbooks arrive with the observability stack.
