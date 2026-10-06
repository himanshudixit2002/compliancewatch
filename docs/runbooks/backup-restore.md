# Backup and restore

Objectives (guide section 17): RPO 15 minutes, RTO 1 hour for the product APIs, exercised in a
quarterly drill. The design targets Aurora PITR and S3 replication; until then the MVP runs
on managed Postgres with the provider's point-in-time recovery (see `infra/deploy/README.md`).

## What holds state

| Store | Contents | Backup | Restore |
| --- | --- | --- | --- |
| Postgres (one schema per service) | Everything durable: profiles, rules, obligations, consents, outbox, ledgers | Managed PITR (Fly Postgres or Neon: continuous WAL); dev: `make dev-backup` writes `var/backups/<timestamp>.dump` | Managed console restores to a point in time; dev: `make dev-restore FILE=...` |
| Raw document store (`CW_PIPELINE_RAW_STORE`: `var/raw` or the S3 bucket) | Fetched regulator documents, content-addressed (`<ab>/<sha256>`), never overwritten; `pipeline.raw_document.storage_key` names each one | Object versioning and cross-region replication in production; dev: the directory | Re-run `make backfill` for the source; the digests match |
| Redpanda | Event topics; the outbox tables are the source of truth | Not backed up: topics are replayable from the outbox (`python -m py_common.outbox` replays `dead` rows) | Recreate topics; the relay republishes pending rows |
| Temporal | Workflow histories | Temporal Cloud keeps them; self-hosted dev uses Postgres | Workflows are idempotent on their inputs and can be restarted |
| Langfuse, Prometheus, Tempo, Grafana | Traces, metrics, dashboards | Retention only (90 days traces, 2 days dev metrics); dashboards are provisioned from the repo | Reprovision |

## Dev stack

```bash
make dev-backup                        # pg_dump -Fc of the compliancewatch database into var/backups/
make dev-restore FILE=var/backups/x.dump   # drops and recreates the database, then pg_restore
```

Both run inside the `postgres` container, so nothing has to be installed on the host.

## Production restore drill (quarterly)

1. Restore the managed database to a fresh instance at a chosen point in time.
2. Point a staging copy of every service at it (`CW_DATABASE_URL`), run `make migrate` against
   it (no-op when the schemas are current) and the smoke checks (`/ready` per service).
3. Replay the outbox: the relay publishes rows still `pending`; consumers are idempotent
   through `processed_event`.
4. Record the time from decision to green smoke checks; above one hour is a finding.

## After a restore

Announce the recovery point to tenants whose obligations or evidence changed in the lost
window; the audit log (when it exists) is the list. Consent records are append-only: a lost
withdrawal is the one thing to re-check by hand (notification preferences are suppressed
until the number opts in again).
