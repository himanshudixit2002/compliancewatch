# Fan-out control

What to do with a rule version's fan-out: hold every fan-out before a risky change, pause one that
looks wrong, resume or cancel it, and find out why one is held, paused or failed. A fan-out
decides one published rule version for every business of its level in the engine's business
directory (ADR-004, its 2026-10-05 addendum); the decisions make and close obligations through
`applicability.decided`, so a bad version reaches every tenant within minutes. The controls stop
it at a batch boundary.

## How it works

- The rulebook publishes a version; `rule.published` reaches the engine's worker (consumer group
  `applicability-engine.rules`). With the flag `applicability.fanout` on
  (`CW_APPLICABILITY_FANOUT_ENABLED`) it records a run in `applicability.fanout_run` and starts
  the workflow `applicability-fan-out-<rule version id>` on the Temporal task queue
  `applicability`. A version fans out once: a second start is refused. With the flag off the run
  is recorded `disabled` and nothing more happens.
- The workflow pages the directory in batches of 1,000 entries, one tenant group at a time. Each
  business's profile is read over HTTP with no transaction open, then its decision (trigger
  `rule_published`, `trigger_ref` `rule.published:<event id>`) is written in one unit of work of
  its tenant. A decision publishes `applicability.decided` when it applies, or when it differs
  from the previous decision of its business and version. Replaying a batch stores nothing twice.
- At every batch boundary the workflow reads the global hold (`applicability.fanout_hold`) and
  its own row. While either stops it, it waits, reading them again every 30 seconds or at once when
  a control signals it. After 100 batches it continues as new with its cursor.
- When the version supersedes another, each business is compared with the superseded version's
  latest decision. Once 200 have been compared, a flip rate above 2% pauses the run by itself.
- Statuses: `running`, `held` (the hold stopped it), `paused` (a person did, or the flip check),
  `completed`, `cancelled`, `disabled`, `failed` (a batch kept failing; `last_error` says why).

Every control is written to `audit.event` in the same transaction as the row, as a row of no
tenant: `applicability.fanout.pause`, `.resume`, `.cancel`, `.hold` and `.release`, with the
actor (the admin's user id; `system:applicability-engine` for the flip check, a withdrawal, or a
caller without a token in `header` mode) and the reason. A run that pauses itself or is cancelled
by a withdrawal writes the same entries as the system.

## The controls

Reads need a regulatory role (analyst, reviewer or admin); controls need an admin. Pausing,
cancelling and holding need a reason of at least ten characters. The web app's internal tools do
all of it on screen (`/admin/fan-outs`, a version's run, the impact explorer;
[docs/web/runbook-admin.md](../web/runbook-admin.md)). On the local product (`make product`) the
internal listener answers without a token:

```bash
API=http://127.0.0.1:8080/v1/applicability-engine
curl -s "$API/fan-outs?limit=20"                       # newest first; next_cursor pages on
curl -s "$API/fan-outs/<rule version id>"              # status, counters, flip_rate, last change
curl -s "$API/fan-out-hold"                            # {"held": false, ...}
curl -s -X PUT "$API/fan-out-hold" -H 'content-type: application/json' \
  -d '{"held": true, "reason": "Deploy of the rulebook in progress"}'
curl -s -X PUT "$API/fan-out-hold" -H 'content-type: application/json' -d '{"held": false}'
curl -s -X POST "$API/fan-outs/<id>/pause" -H 'content-type: application/json' \
  -d '{"reason": "Flips look wrong, checking with the analysts"}'
curl -s -X POST "$API/fan-outs/<id>/resume"
curl -s -X POST "$API/fan-outs/<id>/cancel" -H 'content-type: application/json' \
  -d '{"reason": "Wrong threshold in the predicate"}'
```

In a deployment the same routes are admin routes: the public listener serves them only in
`token` mode, with an admin's access token (`Authorization: Bearer <token>`).

## Before publishing: a dry run

A dry run says what a version would decide before it fans out: approved or still a draft, or a
specification no version holds yet. It evaluates the version against the business directory of
its level as a fan-out would, of one tenant when the scope names one, and answers the counts by
result, the counts by the attribute that decided each result and sample decisions. It stores no
decision and sends nothing; it writes one `applicability.dry_run` row to `audit.event` with the
admin and the counts. A scope over `CW_APPLICABILITY_DRY_RUN_MAX` businesses (2,000) is refused:
name a tenant.

```bash
curl -s -X POST "$API/dry-runs" -H 'content-type: application/json' \
  -d '{"rule_version_id": "<id>", "scope": {"tenant_id": "<tenant id>", "sample_size": 10}}'
```

Many more `applies` or `unsure` results than the change should bring, or an attribute deciding
results it should not touch, is the cue to return the version to draft instead of publishing it.

## Hold every fan-out

Set the hold before anything that could make a whole fan-out wrong: a deploy of the engine or the
ontology, a rulebook data fix, an incident in the profile service. Running fan-outs stop at their
next batch boundary and show `held`; a version published meanwhile starts and stops before its
first batch. Release the hold when done: every held run carries on by itself. A run a person
paused stays paused.

## A run paused itself on flips

`status_reason` says how many of the compared businesses flipped. The superseding version changes
that many results, which is more often a fault than a change of law.

1. Read the version and its predecessor in the rulebook (`GET /v1/rulebook/rule-versions/<id>`)
   and a few flipped decisions (`GET /v1/applicability-engine/businesses/<id>/decisions`).
2. The change is intended: resume. The flip check stays off for the rest of the run, since you
   have seen the flips.
3. The version is wrong: cancel the run, then withdraw the version in the rulebook. The decisions
   already made stay; the obligation service closes the open obligations the version made
   (`rule.withdrawn`, closure reason `rule_withdrawn`) and tells their people. A corrected version
   fans out on its own when it is published.

## A run stays held or paused

- `held`: `GET /fan-out-hold` names who set the hold and why. Releasing it wakes the run at once;
  without the signal (Temporal unreachable from the app) the run sees it within 30 seconds.
- `paused`: `status_by` and `status_reason` say who paused it and why; resume or cancel it.
- Neither, but nothing moves: the worker is not serving the task queue. See
  [temporal-worker.md](temporal-worker.md) (queue `applicability`); the Temporal UI shows the
  workflow `applicability-fan-out-<rule version id>`, its pending activity and its attempts.

## A run failed

A batch failed for about 40 minutes with backoff (the profile service or the rulebook did not
answer), or at once because the version was withdrawn or is not published. `last_error` holds the
cause; the worker log has `activity.failed` lines for `applicability.fanout.evaluate_batch`. The
decisions made before the failure stay. A run does not restart: once the cause is fixed, each
business is decided again when its profile changes (the profile.updated recompute), and a new
version of the rule fans out in full.

## No run for a published version

1. The flag is off for the worker: the run reads `disabled`. Turn the flag on for later
   publications; this version reaches each business when its profile next changes.
2. No run at all: the worker's consumer did not handle `rule.published`. `make product-logs
   PROC=worker` shows `applicability.rule_event` for each event it handled, with `skipped` when
   the rulebook no longer had the version published. A message it could not handle is on
   `rule.published.applicability-engine.rules.dlq`
   (`docker compose exec redpanda rpk topic consume rule.published.applicability-engine.rules.dlq -n 1`);
   replay it after fixing the cause.

## Roll back a version

Cancel its fan-out if it is still running, then withdraw the version in the rulebook
(`POST /v1/rulebook/rule-versions/<id>/withdraw`, or "Roll back this version" on the version's
fan-out page). `rule.withdrawn` cancels a run that has not finished, as the system, and drops the
engine's cached list of the versions in force, so a profile change no longer decides it; the
obligation service closes the obligations the version made.
