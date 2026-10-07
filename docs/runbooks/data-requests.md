# Data requests (DataRequestOverdue)

A tenant asks for a copy of its data (an export) through `POST /v1/identity/data-requests`: its
owner or CA admin for their own tenant, or the regulatory team's admin for a tenant that asked
support, with a reason. Each request is due 30 days after it was made (the data map,
`docs/legal/data-map.md`, until counsel confirms the period). Deletion requests have their kind in
the table already; the route refuses them (422 `identity-data-request-kind-unavailable`) until the
erasure cascade exists.

An export is assembled when the owner downloads it (`GET /v1/identity/data-requests/{id}/export`)
and never stored: identity's own data of the tenant, then the part each service of
`CW_IDENTITY_EXPORT_SOURCES` answers on `GET /v1/<service>/data-export` (profile, the
applicability engine, obligation and notification), called with a token identity mints for
itself (scopes `data:export` and `tenant:act`). A service that does not answer is named in the
bundle (`services_pending`, and its entry says `status: unavailable` with the reason), and the
request stays `in_progress` with that service pending; the download itself still answers 200. The
request completes once every service has answered one download. Each request writes
`data_request.created`, and each download `data_request.exported` naming the services that
answered and those still pending, to the tenant's audit trail.

- `DataRequestOverdue` (page, Identity and Partner): at least one request, of any tenant, is past
  its deadline and not completed, for an hour.

Identity reports `identity_data_requests_open{kind}` (the requests not completed, every tenant's,
zero when none) and `identity_data_requests_overdue` (how many of them are past their deadline)
when `CW_OTEL_ENDPOINT` is set, from a reading it takes at most once a minute. The reading goes
through `identity.data_requests_open()`, a `SECURITY DEFINER` function owned by the NOLOGIN role
`cw_identity_directory` that answers counts per kind and no row: identity's own role sees one
tenant's requests at a time under row-level security. A failed reading logs
`data_request_metrics.read_failed` and reports nothing, so the alert sees a gap rather than a
false zero.

## When it fires

1. See what is overdue, as `cw_identity` or `cw_app` (the roles that may run the function):

   ```sql
   SELECT * FROM identity.data_requests_open();
   ```

   To find which tenant: forced row-level security holds the owner too, so read the rows as the
   directory role (the owner may act as it; a superuser on the dev stack may too), in one
   transaction:

   ```sql
   BEGIN;
   SET LOCAL ROLE cw_identity_directory;
   SELECT id, tenant_id, kind, source, requested_at, deadline_at, status, services_done
     FROM identity.data_request
    WHERE status <> 'completed' AND deadline_at < now()
    ORDER BY deadline_at;
   ROLLBACK;
   ```

2. An export that was never downloaded stays `received`. Nobody but the tenant's owner or CA
   admin downloads it: write to the tenant's owner (the address on their user) that the copy is
   ready on the data rights page, and note it in the support ticket. A support request the
   tenant cannot reach (no active owner) is escalated to the Identity and Partner lead.
3. An export that is `in_progress` names the services still pending (`GET
   /v1/identity/data-requests/{id}` answers `services_pending`). For each one:
   - is the service up, and is its `GET /v1/<service>/data-export` answering for the tenant?
     Identity logs `identity.export_source_failed` with the service and the reason (`answered
     503`, `unreachable (ConnectError)`, `answered the export of another tenant`), never the body;
   - is `CW_IDENTITY_EXPORT_SOURCES` right for this deployment (the combined product points every
     source at its internal listener by itself; separate processes need the addresses)?
   - in token mode, does the service trust identity's keys (`CW_AUTH_JWKS_URL`)? A 401 or 403
     from a source is a key or scope problem, not a data problem.

   Once the service answers, the next download completes the request; ask the owner to download
   again.
4. Never mark a request completed by hand: the deadline is what the tenant was promised, and the
   audit trail must show the export that met it.

## After an incident

Write down which tenant, how late, and why, in the support ticket; a request past its deadline
may have to be reported (docs/legal, counsel to confirm). If a source keeps failing for one
tenant, look for data that service cannot serialise (its logs name the error), and fix it there.

## The directory role

`infra/dev/postgres/roles.sql` makes `cw_identity_directory` (NOLOGIN, no attribute), its read
policy `data_request_directory` (FOR SELECT, `USING (true)`, for that role only) and the function,
once identity's migration 0010 has made `data_request`; `make migrate` and `make db-roles` run it,
and so does a deployment's role step (`infra/deploy/README.md`). Only `cw_identity` and `cw_app`
may run the function. A deployment's owner that is not a superuser is made a member of the role
with `INHERIT FALSE, SET TRUE`: it may create the function as the role, and never reads through
its policy. If the gauges report nothing and the logs say the function does not exist, run the
role step again.
