# Deliberate breaking changes to the OpenAPI specs

`scripts/check_openapi_compat.py` compares every committed spec in this directory with the base
branch and fails on a change that can break a client built against the base: a removed path,
operation or 2xx response, a media type or property removed from a 2xx response, a request body,
property or parameter that became required, a narrowed request enum, or a type change. It runs in
the contracts job on every pull request, and locally as `make openapi-compat BASE=origin/main`.
Specs that are new on the branch are skipped.

A break that is meant starts with an ADR: who calls the operation, how they move, and when the
old shape goes. The pull request that makes the break then adds one row per broken operation to
the table below. The check lets an operation break only when its row is new on the branch. Rows
already on the base branch recorded earlier breaks and allow nothing new, and a new row that
matches no break fails, so a row cannot approve a break in advance. Rows are never removed.

Columns: the spec file name, the operation as `METHOD /path` exactly as the spec writes it, the
reason in one sentence (without a `|`), and the ADR as `ADR-NNN`.

| Spec | Operation | Reason | ADR |
| ---- | --------- | ------ | --- |
