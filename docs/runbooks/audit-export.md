# Audit trail and its export

What the audit trail holds, who may read which part of it, and how to export a range of it to
the object-locked bucket where it is kept for seven years.

## What is audited

Every service writes one row to `audit.event` per audited action, in the transaction of the
action, so the row commits or rolls back with it (`py_common.audit`, guide sections 9, 15 and
16). A row holds the action (`<subject_type>.<verb>`), the tenant whose data it touched (none for
a platform-wide action), the subject's type and id, the actor (a user with the roles they acted
with, a service client, or `system:<service>`; never a name), the reason a person gave, the state
before and after (the changed keys only), the time and the correlation id of the request or
event. Personal identifiers in the reason and the state are masked (`[PAN]`, `[GSTIN]`,
`[PHONE]`, `[EMAIL]`, `[AADHAAR]`). Rows are append-only: a trigger refuses UPDATE and DELETE,
a tenant's erasure included (pseudonymising them on erasure is not built yet).

| Service | Actions | Tenant |
| --- | --- | --- |
| identity | `tenant.created`, `user.invited`, `user.roles_changed`, `user.disabled`, `consent.recorded`, `subscription.started`, `subscription.status_changed` (`system:billing-webhook`) | the tenant |
| identity (`identity-admin`) | `service_client.created`, `service_client.revoked`, `audit.exported` (`system:identity-admin`) | none |
| profile | `profile_node.registered`, `profile_node.attributes_changed`, `profile_node.prefilled` | the tenant |
| obligation | `obligation.created`, `obligation.rescheduled` (one per obligation, with its cause), `obligation.closed`, `obligation.status.start`, `.complete`, `.waive`, `obligation.assign`, `obligation.comment` | the tenant |
| rulebook | `entity_review.decided`, `relation_candidate.approved`, `.rejected`, `rule_version.submitted`, `.approved`, `.returned`, `.published`, `.withdrawn`, `review_task.claimed`, `.drafted`, `.decided` | none |
| applicability engine | `applicability.fanout.pause`, `.resume`, `.cancel`, `.hold`, `.release`, `applicability.dry_run` (none); `applicability.review.resolve` (the reviewed tenant) | as shown |
| notification | `notification.bulk` | the CA firm |
| pipeline | `pipeline.source.add`, `.edit`, `.fetch`, `.backfill`, `pipeline.document.upload`, `.retry`, `pipeline.outbox.requeue`, `pipeline.task.resolve`, `.dismiss` | none |

Volume: most rows follow a person's action. Two grow with the data: `obligation.created` writes
one row per obligation a fan-out materialises, and `obligation.rescheduled` one per open
obligation a deadline change moves. Both are bounded by the obligation rows themselves, which is
fine for the MVP; one row per batch is the change to make if the table grows too fast.

## Who reads what

Identity alone reads the table: `cw_identity` is the only service role with SELECT on it
(`infra/dev/postgres/roles.sql`). Row-level security (identity migrations 0005 and 0006) admits:

- a session's own tenant's rows (`app.tenant_id`);
- the rows of no tenant while `app.audit_scope` is `regulatory`;
- every row while `app.audit_scope` is `export`.

Identity sets the scope only after its own role checks, and names the scope in the query as well,
so a role that bypasses row-level security reads no more.

`GET /v1/identity/audit?subject_type&subject_id&action&from&to&limit&cursor` answers a page of at
most 200 entries, newest first, keyset-paged on (occurred_at, id):

- owners, CA admins and compliance leads read their tenant's entries;
- analysts, reviewers and admins read the platform's entries and their own (internal) tenant's;
- staff, CA staff and services get 403; a request without a token gets 401 outside header mode,
  and in header mode reads only the tenant `x-tenant-id` names, never the platform's rows;
- a cursor the route did not issue, or a `from` not before its `to`, is a 422.

No route reads another tenant's rows for the regulatory team; the export does.

## Exporting a range

Retention is seven years. Export each closed month, upload it to the object-locked bucket, and
keep the manifest with it.

1. Run against the environment's database as identity's role or the schemas' owner, with the
   identity schema on the search path (as `make migrate` sets it):

   ```bash
   CW_DATABASE_URL='<url>' identity-admin audit-export \
     --from 2026-09-01 --to 2026-10-01 --out var/audit-export/2026-09
   ```

   `--from` is inclusive, `--to` exclusive; a date without a time is midnight UTC. The command
   writes `audit-events.ndjson` (one entry per line, oldest first, in the route's JSON shape) and
   `manifest.json` (`file`, `format`, `sha256`, `count`, `range`, `generated_at`), prints the
   manifest, and records an `audit.exported` row of no tenant. A directory that already holds an
   export is refused, so an export is never overwritten.
2. Check the file against the manifest: `shasum -a 256 var/audit-export/2026-09/audit-events.ndjson`
   prints the manifest's `sha256`, and `wc -l` its `count`.
3. Upload both files to the audit bucket under `audit/<YYYY-MM>/`. The bucket has object lock in
   compliance mode with a seven-year retention, so nobody can change or delete them before that
   (infra/deploy/README.md, manual step 8). Uploading is manual until the bucket exists.
4. Delete the local copy once the upload is verified: the export holds every tenant's rows.

An export of a month with no rows is valid: an empty file whose manifest says `count: 0`.

## When something is wrong

- **The route answers 401 for a signed-in owner.** Their session was revoked (roles changed or
  user disabled) or the token expired; they sign in again.
- **An admin sees no platform rows.** Identity's migration 0006 has not run in that environment:
  `make migrate SERVICE=identity` (or the release) and check `pg_policies` for
  `event_platform_read`.
- **A service fails with `permission denied for schema audit`.** Its role lacks the audit grants:
  run `roles.sql` again after the release that created the schema (manual step 3).
- **The export refuses the directory.** It holds an earlier export; name a new directory rather
  than overwrite one that may already be uploaded.
