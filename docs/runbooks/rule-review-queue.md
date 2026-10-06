# Rule review queue (RuleReviewQueueStale)

Rule versions wait for an analyst's decision as review tasks in the rulebook's `review_task`
table: one task per version that is not decided yet, claimed by the analyst working on it or
open for anyone. Until a task is decided its version is not approved, so it cannot be published
and no business gets the duty it describes. Today every task is of kind `seed`: a draft of the
seed calendar (`services/rulebook/seed/gst_calendar.yaml`) that `POST
/v1/rulebook/review/tasks/seed` put in the queue. The rule publication objective is 90% of
versions published within 4 business hours of reaching the queue (guide section 18).

- `RuleReviewQueueStale` (ticket, Regulatory Intelligence): the oldest task not decided yet has
  waited more than 48 hours, for an hour.

The rulebook reports `rulebook_review_task_oldest_open_age_seconds` (how long the oldest task
not decided, claimed or not, has waited since it was opened; 0 when none waits) and
`rulebook_review_tasks_open{regulator}` (the tasks not decided, for every regulator that has had
a task) when `CW_OTEL_ENDPOINT` is set, from a reading of the queue it takes at most once a
minute. A failed reading logs `review_metrics.tasks_read_failed` and reports nothing, so a
rulebook that cannot reach its database shows as missing data rather than as an empty queue.

## Triage

1. How much waits, and where: `GET /v1/rulebook/review/stats` (an analyst's, reviewer's or
   admin's access token in token mode) gives the counts by status and regulator, the decisions
   made, the median time from a task's opening to its decision and the age of the oldest task.
   In Prometheus, `max by (regulator) (rulebook_review_tasks_open)`.
2. Which tasks: `GET /v1/rulebook/review/tasks?status=open` and `?status=claimed` list the queue
   by regulator, higher priority first, then oldest first, with each version's rule key, status,
   whether it is high impact and how many people approved its current round.
3. Read the oldest: `GET /v1/rulebook/review/tasks/{task_id}` shows the version's content, its
   specification as lines, the citations with their verification, the documents they cite, the
   approvers of the round and the history (the decision audit and every task the version had).
   - A task `open` whose version is `in_review` with one approval is a high-impact version
     waiting for a second, different reviewer: the first approver cannot give the second.
   - A task `claimed` for days: its analyst is away or stuck. Only the claimant edits the draft.
   - A seed draft with open questions (`todo`) or no citation: the analyst needs the statute the
     rule cites. Upload it to its statute source (`cgst_act`, `cgst_rules`, `igst_act`) with
     `POST /v1/pipeline/sources/{key}/uploads`; once it is parsed and registered, its clauses
     can be cited ([parse-failures.md](parse-failures.md) when it needs a transcript).
4. In the database (`make dev-psql` locally, schema `rulebook`): `select regulator, status,
   count(*), min(opened_at) from review_task group by 1, 2 order by 1, 2`.

## Fix

- Work the oldest tasks first. An analyst claims a task (`POST .../review/tasks/{id}/claim`),
  edits the draft and cites its clauses (`PATCH .../review/tasks/{id}/draft`; every quote is
  checked against the stored clause), then an analyst, reviewer or admin decides it (`POST
  .../review/tasks/{id}/decide`):
  - `approve` submits the draft and approves it. A high-impact version needs two different
    approvers, counted from the decision audit; the same person twice is refused. Approving does
    not publish: `POST /v1/rulebook/rule-versions/{id}/publish` does, by a reviewer.
  - `return` (with a note) sends the version back to draft and opens a new task for the rework.
    This is also how a task held by an analyst who is away goes back to the queue.
  - `reject` (with a note) closes the task and leaves the version a draft. The next `POST
    .../review/tasks/seed` opens a new task for it, so reject a seed draft only for a reason
    the calendar will fix.
- The writes need `x-cw-review-token` (`CW_RULEBOOK_REVIEW_TOKEN`) without a bearer in header
  and dual mode, or an access token: claiming and editing take the `analyst` role, deciding
  `analyst`, `reviewer` or `admin`. A signed-in user is recorded as the actor whatever the
  body says.
- A seed backlog is expected while the team works through the calendar: the ticket stays open
  until the oldest seed draft is decided, and each one it names is a duty no business gets yet.
  Do not reject drafts to quiet the alert, and never decide tasks with SQL: a decided task never
  changes (the table's trigger refuses it), and the version's transition must go through the
  routes, which commit it with the decision.

## Escalation

The alert is a ticket, not a page: nothing is lost while tasks wait, but the rules they hold are
not published. If the queue is still stale after a working day of review, raise it with the
Regulatory Intelligence lead, who can add reviewers (a high-impact version needs two) or agree
which regulator's tasks go first. A queue that grows because tasks cannot be decided (a route
refusing every decision, a version stuck in review) goes to the rulebook owners as a bug, with
the task ids and the problem types the routes answered.
