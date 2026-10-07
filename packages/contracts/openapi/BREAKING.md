# Deliberate breaking changes to the OpenAPI specs

`scripts/check_openapi_compat.py` compares every committed spec in this directory with the base
branch and fails on a change that can break a client built against the base: a removed path,
operation or 2xx response, a media type or property removed from a 2xx response, a request body,
property or parameter that became required, a narrowed request enum, or a type change. It runs in
the contracts job on every pull request, and locally as `make openapi-compat BASE=origin/main`.
Specs that are new on the branch are skipped.

A break that is meant starts with an ADR: who calls the operation, how they move, and when the
old shape goes. The pull request that makes the break then adds one row per broken operation to
the table below. The check lets an operation break only when the branch adds a row for it. Rows
already on the base branch recorded earlier breaks and allow nothing new, so a later break of an
operation that already has a row adds another row with its own reason and ADR. A new row that
matches no break fails, so a row cannot approve a break in advance. Rows are never edited or
removed, and the check fails on a base row that the branch changed.

Columns: the spec file name, the operation as `METHOD /path` exactly as the spec writes it, the
reason in one sentence (without a `|`), and the ADR as `ADR-NNN`.

| Spec | Operation | Reason | ADR |
| ---- | --------- | ------ | --- |
| rulebook.v1.json | GET /v1/rulebook/review/tasks | A candidate task has no rule version until an analyst drafts one, so its rule_version_id, rule_key, version and version_status are null until then, and every task's kind gains candidate; cw-product's check reads the queue (review_queue and claim_one in tools/demo/src/cw_demo/product/check.py) and changes with it to accept a null version_status and claim seed tasks only | ADR-018 |
| rulebook.v1.json | GET /v1/rulebook/review/tasks/{task_id} | A candidate task not drafted yet has no rule version, so the task's rule_version_id and the detail's rule_version are null, and the kind of the task and of each task in its history gains candidate; cw-product's check reads only the seed task it claimed (read_task) | ADR-018 |
| rulebook.v1.json | POST /v1/rulebook/review/tasks/{task_id}/claim | A candidate task not drafted yet has no rule version, so the claimed task's rule_version_id is null, and its kind gains candidate; cw-product's check claims a task (claim_one) and changes with it to claim seed tasks only | ADR-018 |
| rulebook.v1.json | PATCH /v1/rulebook/review/tasks/{task_id}/draft | The response is the task detail, whose task rule_version_id and rule_version are null for a candidate task not drafted yet, and whose tasks' kind gains candidate; no client calls it yet | ADR-018 |
| rulebook.v1.json | POST /v1/rulebook/review/tasks/{task_id}/decide | A candidate rejected before it was drafted has no version, so the decision's version and the task's rule_version_id are null, and the task's kind gains candidate; no client calls it yet | ADR-018 |
| identity.v1.json | POST /v1/identity/billing/subscriptions | The route now requires an Idempotency-Key so a retry never starts a second subscription at the payment provider; the only client is the web app's billing form, which mints a key per attempt and sends the same key on a retry of that attempt | ADR-021 |
