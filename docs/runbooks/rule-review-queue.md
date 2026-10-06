# Rule review queue (RuleReviewQueueStale)

Rule versions, and the rule candidates the pipeline extracts, wait for an analyst's decision as
review tasks in the rulebook's `review_task` table: one task per version, and per candidate, that
is not decided yet, claimed by the analyst working on it or open for anyone. Until a task is
decided its version is not approved, so it cannot be published and no business gets the duty it
describes. Two kinds share the queue:

- `seed`: a draft of the seed calendar (`services/rulebook/seed/gst_calendar.yaml`) that `POST
  /v1/rulebook/review/tasks/seed` put in the queue, at priority 50.
- `candidate`: a rule candidate the pipeline extracted from a regulator document, which the
  rulebook worker took in from rule.candidate.created (group `rulebook.rule-candidates`, flag
  `rulebook.candidate_intake`). It has no version until an analyst drafts one from it. Its
  priority says what it needs: 100 when it looks high impact (it extends a deadline or
  withdraws something, applies to every taxpayer, or names amounts), 80 when there is no
  candidate to draft from (the extraction was unparseable, so an analyst drafts the rule by hand
  from the document), 50 when the extraction asked for review or a validator found an issue, 10
  otherwise. The queue lists higher priorities first within a regulator.

The rule publication objective is 90% of versions published within 4 business hours of reaching
the queue (guide section 18).

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
   made, the median time from a task's opening to its decision, the age of the oldest task, and
   the candidates decided with the acceptance rate (approved without an edit over decided). In
   Prometheus, `max by (regulator) (rulebook_review_tasks_open)`.
2. Which tasks: `GET /v1/rulebook/review/tasks?status=open` and `?status=claimed` list the queue
   by regulator, higher priority first, then oldest first, with each version's rule key, status,
   whether it is high impact and how many people approved its current round; `&kind=candidate`
   or `&kind=seed` keeps one kind. A candidate task not drafted yet shows its candidate's title,
   suggested rule key and suggested impact, and no version.
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
   - A candidate task shows its `candidate`: the extraction as stored, the document
     (`document_id`; the file is at the pipeline's `GET /v1/pipeline/documents/{document_id}/raw`),
     the draft it proposes with `problems` (what does not map), why it looks high impact, and
     whether a rule has the suggested key (`suggested_rule_known`; the pipeline's key is a guess
     from the form and the cadence, never a lookup).
4. In the database (`make dev-psql` locally, schema `rulebook`): `select kind, regulator, status,
   count(*), min(opened_at) from review_task group by 1, 2, 3 order by 1, 2, 3`, and the
   candidates by status: `select status, count(*) from rule_candidate group by 1`.

## Fix

- Work the queue in its order: higher priority first, then the oldest. An analyst claims a task
  (`POST .../review/tasks/{id}/claim`). For a candidate task they first draft a version from the
  candidate (`POST .../review/tasks/{id}/draft`, once per candidate): the rule key it belongs to
  (with `new_rule`, its regulator and level, for a key no rule has), the edits to what the
  candidate proposes (a 422 `rulebook-draft-incomplete` lists every problem, and nothing is
  stored), the citations when the candidate's quotes are not the ones to cite, and the relation
  candidates of the document to approve onto the draft (an `extends_deadline` needs its target
  version). Then they edit the draft and cite its clauses (`PATCH .../review/tasks/{id}/draft`;
  every quote is checked against the stored clause), and an analyst, reviewer or admin decides it
  (`POST .../review/tasks/{id}/decide`):
  - `approve` submits the draft and approves it. A high-impact version needs two different
    approvers, counted from the decision audit; the same person twice is refused. Approving does
    not publish: `POST /v1/rulebook/rule-versions/{id}/publish` does, by a reviewer.
  - `return` (with a note) sends the version back to draft and opens a new task for the rework.
    This is also how a task held by an analyst who is away goes back to the queue.
  - `reject` (with a note) closes the task and leaves the version a draft. The next `POST
    .../review/tasks/seed` opens a new task for it, so reject a seed draft only for a reason
    the calendar will fix. A candidate task's rejection also names a `reason`: `not_a_rule`
    (the document states no rule), `wrong_extraction` (the model read it wrongly), `duplicate`
    (another candidate or rule holds it), `out_of_scope` (a rule the product does not cover) or
    `unparseable` (nothing to draft from, and the analyst will not draft it by hand). It rejects
    the candidate, before or after drafting, and writes rule.rejected; a draft made from it
    stays a draft, since no transition discards one, so prefer `return` when the draft is worth
    another round. A candidate task not drafted yet can only be rejected.
- The writes need `x-cw-review-token` (`CW_RULEBOOK_REVIEW_TOKEN`) without a bearer in header
  and dual mode, or an access token: claiming and editing take the `analyst` role, deciding
  `analyst`, `reviewer` or `admin`. A signed-in user is recorded as the actor whatever the
  body says.
- A seed backlog is expected while the team works through the calendar: the ticket stays open
  until the oldest seed draft is decided, and each one it names is a duty no business gets yet.
  Do not reject drafts or candidates to quiet the alert, and never decide tasks with SQL: a
  decided task never changes (the table's trigger refuses it), and the version's transition must
  go through the routes, which commit it with the decision.
- Candidates arrive only while the intake is on and the worker consumes Kafka. A candidate that
  never became a task is in the consumer's dead letters,
  `rule.candidate.created.rulebook.rule-candidates.dlq` (its `error` header says why: a document
  the rulebook does not store yet, or a payload its contract refuses); replay it once the cause is
  fixed. A failed extraction is run again by ingesting the stored document again.

## Escalation

The alert is a ticket, not a page: nothing is lost while tasks wait, but the rules they hold are
not published. If the queue is still stale after a working day of review, raise it with the
Regulatory Intelligence lead, who can add reviewers (a high-impact version needs two) or agree
which regulator's tasks go first. A queue that grows because tasks cannot be decided (a route
refusing every decision, a version stuck in review) goes to the rulebook owners as a bug, with
the task ids and the problem types the routes answered.
