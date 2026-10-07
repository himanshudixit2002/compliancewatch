# Admin tools

The internal tools under `/admin`, for the regulatory roles (`analyst`, `reviewer`, `admin`) of
the internal tenant. Each tool is a registry entry in the `admin` section
([screens.md](screens.md) lists them with their status); a tool that is not built is served by
`admin/[...slug]` with the notice naming what it waits for. This page describes the tools that
are built: what each shows, what it calls and what waits.

The admin layout runs `requireAdmin()` before anything renders, so a tenant role gets the root
404 with no admin markup; each page calls its gate again on its first line
(`requireScreenSession`), and a regulatory role a tool's entry does not list gets the not-found
page as well ([auth-and-roles.md](auth-and-roles.md)). The flags, ontology, notification,
template, rulebook, review queue, decision review, fan-out, impact, LLM gateway, review task,
system, source and pipeline pages, and the review workbench and stats, each have a sibling
`loading.tsx` with a skeleton (the console's sits in the route group `(console)`, the rule version
list's, the fan-out list's and the source list's in `(list)`, the resolve tool's in `(resolve)`,
the three review queues' in `(queue)` and the pipeline's operations' in `(operations)`, so each
wraps that page alone, as the home's sits in `(home)`); under one, a
not-found answer (an unknown id, a regulatory role the tool does not list) is streamed with status
200 and a `noindex` tag rather than a 404 status, as on the business pages (D-029 in
[decisions.md](decisions.md)). A tenant role still gets the real 404 from the layout's gate. The
document tool has no loading boundary, so its unknown ids stay real 404s (D-037).

| Tool                | Route                                    | Who                     | Calls                                                                 |
| ------------------- | ---------------------------------------- | ----------------------- | --------------------------------------------------------------------- |
| Internal tools      | `/admin`                                 | every regulatory role   | the review queues, rules and prompts (one page each), every `/health` |
| Documents           | `/admin/rulebook/documents`, `/[id]`     | every regulatory role   | `GET /v1/rulebook/documents/{document_id}`                            |
| Feature flags       | `/admin/flags`                           | every regulatory role   | none: `packages/flags/registry.json` and the web server's flag reader |
| Ontology            | `/admin/ontology`                        | every regulatory role   | `GET /v1/ontology` (profile; no tenant header, cached an hour)        |
| Notifications       | `/admin/notifications`, `/[id]`          | `analyst`, `admin`      | `GET /v1/notification/notifications`, `.../{notification_id}`, for the tenant looked up |
| Message templates   | `/admin/notifications/templates`         | every regulatory role   | `GET /v1/notification/templates` (cached five minutes)                |
| Rule versions       | `/admin/rulebook/versions`               | every regulatory role   | `GET /v1/rulebook/rule-versions`, `.../rules`, `.../rules/{rule_key}/versions` |
| Rule version        | `/admin/rulebook/versions/[id]`          | every regulatory role   | the version, its citations and their clauses, its relations, the ontology; citations and the publish workflow with the review token behind `web.publish_actions` |
| Canonical entities  | `/admin/rulebook/entities/canonical`     | every regulatory role   | `GET /v1/rulebook/entities/resolve`                                   |
| Canonical entity    | `/admin/rulebook/entities/canonical/[id]`| every regulatory role   | the entity, the clauses that mention it, the relations to it and their versions |
| Clause search       | `/admin/rulebook/search`                 | every regulatory role   | `POST /v1/rulebook/search` (the words posted, never in the address)   |
| Relations graph     | `/admin/rulebook/relations/graph`        | every regulatory role   | `GET /v1/rulebook/relations` and each version it reaches              |
| Entity review       | `/admin/rulebook/entities`               | every regulatory role   | `GET /v1/rulebook/review/entities`                                    |
| Entity group        | `/admin/rulebook/entities/group?type=&name=` | every regulatory role reads and decides | `GET /v1/rulebook/review/entities/items`; `POST .../review/entities/decisions` through `server/api/rulebook-write.ts`, behind `web.admin_rulebook_writes` |
| Relation candidates | `/admin/rulebook/relations`              | every regulatory role   | `GET /v1/rulebook/review/relations`                                   |
| Relation candidate  | `/admin/rulebook/relations/[candidateId]`| every regulatory role reads and decides | the list's keyset for the candidate, its evidence clause, the rules and their versions; `POST .../{candidate_id}/approve` and `/reject` through `server/api/rulebook-write.ts`, behind `web.admin_rulebook_writes` |
| Rules               | `/admin/rulebook/rules`                  | every regulatory role   | `GET /v1/rulebook/rules` (cached five minutes)                        |
| Review queue        | `/admin/review`                          | every regulatory role reads, claims and opens the seed tasks | `GET /v1/rulebook/review/tasks` and `.../review/stats`; `POST .../tasks/{task_id}/claim` and `POST .../tasks/seed` through `server/api/rulebook-write.ts`, behind `web.admin_rulebook_writes` |
| Review workbench    | `/admin/review/[taskId]`                 | every regulatory role reads, claims, drafts, edits, returns and rejects; a reviewer or an admin approves | the task (`GET .../review/tasks/{task_id}`), each document it rests on (`GET /v1/rulebook/documents/{document_id}`, cached) with the pipeline's record of its file (`GET /v1/pipeline/documents/{document_id}`), the ontology and the rule's versions; for a candidate's draft the document's open relation candidates, the rules and their versions; `POST` and `PATCH .../tasks/{task_id}/draft` and `POST .../decide` through `server/api/rulebook-write.ts`, behind `web.admin_rulebook_writes` |
| Review stats        | `/admin/review/stats`                    | every regulatory role   | `GET /v1/rulebook/review/stats`                                       |
| Decision review     | `/admin/decisions`                       | every regulatory role reads; a reviewer or an admin settles | `GET /v1/applicability-engine/review-items`, `POST .../{item_id}/resolve`, for the tenant looked up; each version from the rulebook |
| Fan-outs            | `/admin/fan-outs`                        | every regulatory role reads; an admin holds | `GET /v1/applicability-engine/fan-outs`, `GET` and `PUT .../fan-out-hold`; each version from the rulebook |
| Fan-out control     | `/admin/fan-outs/[ruleVersionId]`        | every regulatory role reads; an admin controls | the run, the hold, `POST .../fan-outs/{id}/pause`, `/resume`, `/cancel`; the version and its withdraw (`server/api/rulebook-write.ts`, `web.publish_actions`) |
| Impact explorer     | `/admin/impact`                          | `admin`                 | `POST /v1/applicability-engine/dry-runs`; the ontology for the attributes |
| Prompts             | `/admin/llm/prompts`                     | every regulatory role   | `GET /v1/llm-gateway/prompts` (cached five minutes, no tenant header) |
| Model routes        | `/admin/llm/models`                      | every regulatory role   | `GET /v1/llm-gateway/models` (cached five minutes, no tenant header)  |
| Usage and budgets   | `/admin/llm/usage`                       | every regulatory role   | `GET /v1/llm-gateway/usage` (no tenant header), once per feature or once for the question asked |
| Profile review tasks| `/admin/profiles/review-tasks`           | every regulatory role   | `GET /v1/profile/nodes/{node_id}`, `.../review-tasks`, `.../snapshot`, for the tenant looked up; the ontology |
| Sources             | `/admin/sources`                         | every regulatory role   | `GET /v1/pipeline/sources` and the schedule's latest run (`GET /v1/pipeline/runs?trigger=schedule&limit=1`); the crawl flag as `packages/flags/registry.json` declares it |
| Source              | `/admin/sources/[key]`                   | every regulatory role reads; an admin changes | the sources (for its record), `GET .../sources/{key}/documents`, its latest runs; `PATCH .../sources/{key}` and `POST .../fetch` through `server/api/pipeline-write.ts`; an upload-only source's upload through `/api-bff/pipeline/sources/[key]/uploads` |
| Pipeline            | `/admin/pipeline`                        | every regulatory role reads; an admin requeues | `GET /v1/pipeline/runs`, `.../documents` or `.../outbox/dead`, and the sources' keys; `POST .../outbox/{event_id}/requeue` |
| Stored document     | `/admin/pipeline/documents/[documentId]` | every regulatory role reads; an admin retries | `GET /v1/pipeline/documents/{document_id}`; `POST .../retry` with an Idempotency-Key; the stored file through `/api-bff/pipeline/documents/[documentId]/raw` |
| Pipeline tasks      | `/admin/pipeline/tasks`                  | every regulatory role reads; an admin resolves | `GET /v1/pipeline/tasks`; `POST .../tasks/{task_id}/resolve` and `/dismiss` |
| System              | `/admin/system`                          | every regulatory role   | `GET /health` and `GET /ready` of every service; the screen registry; the web server's settings |

## Internal tools: `/admin`

The counts of the review queues and registries, each in its own tile with its own error state,
every service's health probed from the web server, and the tool list from the registry grouped
like the sidebar, each tool with its status and the services it depends on (D-036).

## Documents: `/admin/rulebook/documents`

Opens one rulebook document by its id or the sha256 of its source file; the viewer shows the
source facts and every clause with an anchor, and marks a clause or a span from a link (D-037).

## Feature flags: `/admin/flags`

Every entry of the shared flag registry, [`packages/flags/registry.json`](../../packages/flags/registry.json),
read from the `@compliancewatch/flags` module built into the app (no service is called):

- the name, whether it is on or off or one of several values, the variable the code reads for it,
  and for a tenant-targeted flag its allow-list variable;
- what it does and the condition under which it is removed;
- the owner and the default (off for every bool flag; a string flag's default with its values);
- the expiry date, with a badge once it is 30 days away or less ("N days left", "Expires today")
  and once it has passed ("Expired"; `make flags-check` fails on such a flag, so it is only seen
  between the date and the fix);
- the value on the web server, for the flags the web app reads (`services` holds `web`): what
  `server/flags.ts` answers for the session's tenant, through the provider `CW_FLAGS_PROVIDER`
  names. A flag only other services read says which ones read it; their values live in their
  own processes and Unleash, which the web server cannot see, so none is guessed.

The summary counts the flags, the web flags that are on, and those near or past their expiry.
When the web server's reader cannot be configured (Unleash chosen without its address, say), the
page shows the reason as an error and no value, since every web flag would read as off. There is
no control that changes a flag: a flag moves through its variable in local and test, or through
Unleash ([feature-flags.md](feature-flags.md)).

## Ontology: `/admin/ontology`

The business attributes a profile holds, read from the profile service's `GET /v1/ontology`
through `server/ontology.ts` (no tenant header; cached an hour under `profile:ontology`, the
lifetime the service states; D-024). Nothing is restated in the web app: every question, help
line, meaning and value label is the service's.

- The facts: the attribute set's version, the wording's version and language, whether an analyst
  has reviewed the wording (`review_status`), and the number of attributes.
- One table per level of the business hierarchy that holds attributes (the legal entity, a
  registration, a location; ADR-016), in the ontology's order, which is the order onboarding asks
  in. Each attribute shows its key, its type and where its value comes from (pre-filled from the
  GSTIN lookup, asked, or worked out by the service), whether it is stated per financial year, the
  question and help line (or that it is not asked), its meaning, the allowed values with their
  labels or a number's bounds, the ontology's example worded with the labels, and the operators a
  rule predicate may use on its type.
- An attribute whose type, level or source the web app does not know is left out and named in a
  warning, so a new kind on the service shows up as a gap rather than as the wrong text.
- The page is read-only: the ontology changes with a release of `packages/ontology`.

The usage per attribute (how many profiles hold it and in which state, and the rules that read it)
is the registry entry `admin.ontology.usage`, a component of this page that waits for
`GET /v1/profile/admin/attribute-usage` (services track, WP30). The page shows a note built from
that entry naming the route (D-039 in [decisions.md](decisions.md)).

## Notifications: `/admin/notifications`

The notification console, read-only, for the analyst and the admin. The notification routes are
tenant-scoped: a request names one tenant in `x-tenant-id` and sees that tenant's notifications
only, of one business at a time (the list needs `business_id`). The console is therefore a lookup,
as the profile review-task lookup is designed:

- A GET form takes the tenant id and the business id (ids, not personal data, so they sit in the
  query string and a lookup can be shared or bookmarked); a value that is not a UUID is marked on
  its field and nothing is read. The gateway is built with that tenant as `ClientContext.tenantId`,
  the one way a request acts for a tenant other than the session's ([data-layer.md](data-layer.md)).
- The history is the reminders pages' (D-040): newest first, 25 to a page with the service's
  cursor, filtered by delivery state with a GET form that keeps the lookup, each row named by its
  template with the occasion, channel, masked address, state, attempts and times. The service
  answers an empty page for a business id it holds nothing about, so the empty state says to check
  both ids. A failed read shows the problem and its correlation id under the form.
- `/admin/notifications/[notificationId]?tenant=<id>` is one notification: the record with the
  channel's last error, every time it moved and the values it was filled with, plus the ids an
  operator traces a delivery by (business, obligation, recipient, dispatch, the provider's message
  id). Opened without its tenant, the page asks for it with a GET form back to the same
  notification; an unknown id for that tenant is the not-found page.

Resending a notification that failed for good is not offered. The route on `main`
(`POST /v1/notification/notifications/{id}/resend`) takes no reason, checks no admin role and
needs no Idempotency-Key; the services track hardens it (WP30: a reason, the admin role, an
Idempotency-Key, an audit row). The registry keeps the action as its own entry,
`admin.notification.resend`, a capability of the notification page for the admin role, waiting
on the route with the `Idempotency-Key` header it must require (D-041), and the page shows an
admin what it waits for, from that entry.

## Message templates: `/admin/notifications/templates`

Every message template the notification service holds (`GET /v1/notification/templates`, the same
for every tenant, cached five minutes under `notification:templates`), by message, channel and
language: the name it carries at Meta, its approval status there (every template is a draft until
it is submitted from the Meta business account), its placeholders and its text. The text holds
placeholders only; the facts a message carries come from the rulebook and the obligation when it
is sent. The page sits under the console's route, so it is built with it: a static route beside
`/admin/notifications/[notificationId]` keeps `templates` from being read as a notification id.

## Rule versions: `/admin/rulebook/versions`

Every version of the rulebook's rules, by rule key. A row names the version (`rule_key v2`, which
opens its page) and its title, its status, whether an analyst has reviewed it ("Not yet reviewed"
until an approval completes a review round), its effective period, the approvers it needs (one,
two different ones for a high-impact version) and its open questions, and when it was published.

- Status chips choose the list. **In force** (the default) is the rulebook's as-of read, `GET
  /v1/rulebook/rule-versions?as_of=`: the published or superseded version of each rule whose period
  covers the date (today in IST unless the date field says otherwise), paged by rule key with the
  route's `after` cursor. A draft is never in force, so on a stack where nothing is published the
  list is empty and says so, with the way to the drafts.
- **Draft**, **In review**, **Approved**, **Published**, **Superseded**, **Withdrawn** and **Every
  status** read each rule's versions (`GET /v1/rulebook/rules`, then `GET
  /v1/rulebook/rules/{rule_key}/versions`, the only read that returns drafts), eight rules at a
  time from the cursor until a page holds 25 rows, and page on after the last rule read (D-043).
- A rule select narrows either list to one rule. The chips and the form are links and GET requests
  (rule keys and dates are not personal data), so a list can be shared; a malformed date or rule key
  is marked on its field and nothing is read. Nothing is cached: versions move through review
  outside this server too.

## Rule version: `/admin/rulebook/versions/[ruleVersionId]`

One version for the analyst who reviews it: the facts (rule, version, status, review, regulator,
the level it applies to, its period, publication, high impact, id), a warning while it needs review,
the summary, the condition in words, the obligation it creates and how it recurs, the cited
instrument, the open questions, its citations, its relations and the publish workflow, and the
four open mappings as stored at the foot.

- **The condition in words.** The kernel's predicate tree (`all_of`, `any_of`, `not`,
  predicates) is described, not evaluated: each predicate names its attribute with the ontology's
  meaning, the operator in words ("is one of", "is at least") and each value with the ontology's
  label; free text is shown as what has to be judged, an attribute the ontology does not hold is
  marked, and a node of a shape the web app cannot read is shown as stored. Without the ontology
  (`GET /v1/ontology` failed) the values are shown as stored and the page says why.
- **Citations** (`GET .../citations`): each cited clause (read from `GET /v1/rulebook/clauses/{id}`,
  cached five minutes under its tag) with its document, the quote, the clause's text with the quote
  marked when it appears word for word, and the verification (verified or not, the match score, when).
  While the version is a draft the form cites more: rows of a clause id and a quote, sent together
  by `PUT .../citations`. The rulebook stores every row or none: a quote it cannot find in its
  clause, or a clause it does not hold, refuses the whole request; the form keeps the rows, lists
  every failure the rulebook gave and puts each one on its row when it can tell which row it is
  (it reads the rows' clauses for their references). A save says how many citations are new and
  each quote's score, and the table shows them. Past draft, the section says citations change only
  in a draft.
- **Relations** (`GET /v1/rulebook/relations?published_only=false`, from and to the version): what
  it says about other versions and entities, and what other versions say about it, each with its
  evidence clause opened in the document, the version at the other end named by rule key and
  number (read for the purpose), and a link to the graph.
- **The publish workflow.** The steps the version's status allows, as the rulebook's routes state
  them: submit a draft (optionally as high impact, which a later submission keeps), approve or
  return a version in review, publish or return an approved one, withdraw a published one.
  Submitting and returning are every regulatory role's; approving, publishing and withdrawing are a
  reviewer's or an admin's (`admin.review.approve`, `admin.publish`, D-043): an analyst is not
  offered them, the panel names them instead, and the action refuses them before any request. Each
  opens a dialog that says what the rulebook records; return and withdraw ask for a reason of ten
  characters or more (`ReasonDialog`), the others take an optional note (`ConfirmDialog`). The
  acting analyst is the session's user, filled in by `server/api/rulebook-write.ts`, never a form
  field, and an approval is never sent as synthetic. The panel says what the step did and lists the
  round's approvers from the rulebook's answer ("1 of 2 approvals in this round. It needs a second
  approver: a different reviewer or admin.", the signed-in reviewer named); every refusal (the same
  reviewer approving twice, citations missing or unverified, an overlap, a relation that cannot
  take effect, publishing turned off) is shown under the step with the rulebook's title, detail and
  correlation id. On success the page renders again in the new status.
- Citations and steps are sent only with `web.publish_actions` on for the session's tenant and
  `CW_WEB_RULEBOOK_REVIEW_TOKEN` set; otherwise the page shows the refusal (which names the flag or
  the variable) and offers nothing. The rulebook's version read does not carry the round's
  approvers yet, so before a step the panel says they show after one.

## Canonical entities: `/admin/rulebook/entities/canonical`

The resolve tool. A GET form takes an entity type (the kernel's ten) and a name, and shows what the
rulebook's alignment would make of it (`GET /v1/rulebook/entities/resolve`): the status in words
with what it means (resolved, ambiguous, not found, unqualified, empty), the name after the
kernel's normalisation, and the entities it points at to open: the one entity for a resolved name,
every candidate sharing an ambiguous alias. No route lists the entities, so this is the way to one.

## Canonical entity: `/admin/rulebook/entities/canonical/[entityId]`

One entity: its type, canonical name, aliases and id; the clauses that mention it, newest document
first (`GET .../clauses`, 50 at most), with every mention marked in code points and a link to the
document with the first mention marked; with a date (a GET form), only documents published by
then, each clause saying whether its rule is out of force on it; and the relations rule versions
state about it (`GET /v1/rulebook/relations?to_entity_id=`), each source version named.

## Clause search: `/admin/rulebook/search`

The rulebook's hybrid search (`POST /v1/rulebook/search`). The words, a regulator, document types, a
publication date and how many hits are posted to a server action, so the words never reach an
address; the form keeps them after a search. Each hit shows its clause and document, the text with
the searched words marked (`HighlightMark`, where a clause word starts with one), the fused score,
the rank in the full-text leg and in the vector leg as the rulebook returned them, the published
versions citing it, whether its rule is out of force, and a link to the clause in its document.
The page sends the words without an embedding, so the vector leg does not run from here and says
so (D-044).

## Relations graph: `/admin/rulebook/relations/graph`

The relations around one rule version, one or two relations out, every relation or only those of
published versions (a GET form; a version's page links here). The walk reads the relations from and
to each version it reaches, and those to each aligned entity, up to 40 nodes (the page says when it
stops short), and reads each version for its name. The graph is an inline SVG laid out in columns
(the start in the middle, what it points at to the right, what points at it to the left), hidden
from assistive technology; a table beside it lists the same relations with their links and
evidence. No graph library is used (D-044). An id the rulebook does not hold is answered on the
form's field.

## Entity review: `/admin/rulebook/entities`

The mentions the rulebook's alignment could not settle by itself, one row per (entity type,
proposed name) group, in the rulebook's order (by type, then name), 25 to a page: the name (a
link to the group's page), the type, how many mentions are open and the first of them with why it
is open (no entity has the name, several share it as an alias, the mention names nothing, a section
or rule lacks its statute) and a link marking it in its document. A GET form chooses one type; the
pages continue after the last group shown (`after_type` and `after_name`, an empty name included),
so a page has its own address. The queue is read fresh on every visit, as the admin home reads it
(D-036): the pipeline fills it and decisions empty it outside this server (D-055). An empty page
says why in its own words: nothing waits at all, nothing of the chosen type (with the way to every
type), or nothing after the previous page, where the first page is always offered.

## Entity group: `/admin/rulebook/entities/group?type=&name=`

One group, named by the query rather than a path segment: a proposed name may hold a slash
(`01/2000-example`), `@` and spaces, and an empty name is a group too (D-055). The page shows the
type, the name and how many mentions are open, every open mention with why it is open and a link
marking it in its document, a link asking the canonical entities tool how the name resolves today,
and the decision. The rulebook lists at most 200 open mentions of a group, so a list of 200 is
counted as "200 or more (the first 200 listed)" in the facts, the table's caption, the line saying
what the decision covers and the dialog: a decision over the whole group covers every open mention,
listed or not, and the page never states a count it does not know.

- **Make the entity**: the rulebook makes the canonical entity with the proposed name (or finds the
  one that has it) and aligns the mentions to it; **Add the name to an entity**: the name becomes
  another name of an existing entity of the type, named by its id (the resolve tool finds the id);
  **Reject the mentions**: they close as rejected with one of the rulebook's reasons (not an
  entity, the wrong type, a slip in the source text, out of scope).
- The decision covers the mentions the analyst includes, or every open mention when none is
  included. A name that cannot name an entity (empty, or a section or rule without its statute)
  cannot make one and is decided by its mentions, as the rulebook's own rule says; the form says so
  and the action checks it again.
- An optional note (at most 2000 characters), then a dialog that says what the rulebook records:
  on each decided mention the decision, the signed-in user as `decided_by` (filled by
  `server/api/rulebook-write.ts`, never a form field), the note and the time; making an entity or
  adding a name also points the relation candidates that name it at the entity. Nothing else is
  written.
- The panel then shows the rulebook's answer (the status, how the name was resolved, the entity
  with a link to its page, the mentions closed and the candidates updated) and stays on the page
  when the last mention is decided, beside the empty state. A refusal (an entity of another type,
  a name that is not canonical) is shown with the rulebook's problem. Mentions decided before the
  decision arrived (often the analyst's own decision, sent again after its answer was lost: the
  route takes no Idempotency-Key) are information, not an error: the group is read again, the
  page renders with what is open now, and the panel says they were already decided. Who decided
  them is not shown, since the group read lists open mentions only.
- The decision is offered only with `web.admin_rulebook_writes` on for the session's tenant and
  `CW_WEB_RULEBOOK_REVIEW_TOKEN` set; otherwise the page names the flag or the variable and lists
  the mentions read-only. Without a group in the address the page says how to open one.

## Relation candidates: `/admin/rulebook/relations`

What the pipeline proposed each document says about a rule or an entity (a deadline extended, a
version superseded), in the rulebook's id order, 25 to a page with the route's `after` cursor.
Status chips choose open (the default), approved or rejected; a GET form narrows the list to one
document by its id. A row shows the relation (a link to the candidate's page, which carries the
status it was listed in), the period and new due date of a deadline, the target with whether it is
aligned to an entity and the rule key it names, the evidence quote with a link marking its clause
in the document, the quote match and the confidence as percentages, whether the pipeline flagged it
and the issues it raised, and the status. Read fresh on every visit. An empty page says which case
it is: nothing in the status, nothing in the status for the document named, or nothing after the
previous page, where the first page is always offered.

## Relation candidate: `/admin/rulebook/relations/[candidateId]`

One candidate. No route reads a candidate by its id, so the page reads it through the list's
keyset: one row after the id just before it, in the status the address names first and then the
others (D-055); an id no status holds is the not-found page. The page shows the facts (the status,
the relation, the target with its alignment, linking the entity or its review group, the rule key,
the deadline, the scores, the model and prompt that proposed it, who decided it and why it was
rejected), the issues the pipeline flagged, and the evidence clause (read from
`GET /v1/rulebook/clauses/{id}`, cached under its tag) with the quote marked where the clause holds
it word for word, else the quote alone.

- **Approve** writes a rule relation from a draft version: the form offers the drafts that are not
  closed (a closed draft's rule candidate was rejected, so it never moves on), read from every
  rule's versions, and the version it points at: required for the relations that only point at a
  version (supersedes, extends a deadline, corrects, withdraws) and for a candidate that names its
  target rule (whose versions are offered then), optional otherwise, when the relation points at the
  aligned entity. The dialog names both versions. When it is sent, the action reads the candidate
  and every rule's versions again and refuses, on its field and before anything reaches the
  rulebook, a draft or a target the page would not offer (D-061); whether a target is needed comes
  from that read, never from the page.
- **Reject** takes one of the rulebook's reasons (the wrong kind, the wrong target, not in the
  text, a duplicate, out of scope).
- Both take an optional note and record the signed-in user as `decided_by`. The panel shows the
  answer (the rule relation written, with a link to the relations graph around the draft) and stays
  on the page as the candidate renders again in its new status; every refusal (a draft that is not
  editable or closed, a target that is not aligned, a supersession cycle) comes with the rulebook's
  problem. A candidate decided before the decision arrived is read again and shown as information:
  "already decided", approved or rejected (with the reason), by whom ("you" for the signed-in
  analyst, whose earlier answer may have been lost), and the page renders in that state. A decided
  candidate offers nothing. The same flag and token as the entity group apply.

## Rules: `/admin/rulebook/rules`

Every rule the rulebook lists, by key in code point order (the order it pages them in), with the
regulator, the title of its latest version (a rule whose only drafts are closed is left out by the
rulebook), its id to copy and a link to all its versions on the rule version list
(`?status=all&rule=`). A filter typed over the list keeps the rules holding every word in the key,
the title or the regulator and announces how many are shown. The read is the cached rule list
(five minutes under `rulebook:rules`, as the admin home counts it). Read-only: a rule arrives with
its first version.

## Review queue: `/admin/review`

The rulebook's review tasks: the seed calendar's drafts waiting for an analyst and the rule
candidates the pipeline extracted, each to be approved, returned or rejected, in the rulebook's
order (by regulator, higher priority first, then the oldest), 25 to a page with the rulebook's
opaque cursor (D-065). Read fresh on every visit.

- **The strip**: how many tasks are open, claimed and decided, the acceptance rate of the rule
  candidates and how long the oldest open task has waited, from the stats, with the stats page. A
  failed stats read shows in the strip's place and leaves the queue.
- **Open seed tasks** opens a task for each seed draft that needs review and has none waiting
  (`POST /v1/rulebook/review/tasks/seed`) and says how many, or that every draft already has one;
  pressing it again opens nothing.
- **The filters**, each a row of chips in the address: the status (open by default, claimed,
  decided, every status), the kind (seed draft or rule candidate) and the regulator (those the
  stats count). A row shows the task's kind, its title (the version's, or the candidate's before
  drafting) linking the workbench, the rule key and version (or the key the candidate suggests),
  the version's status, the approvals as "k of required" and high impact, a candidate's outcome,
  confidence, issue count and whether it asked for review, who claimed it and when, and the
  decision. The rulebook has no assignee filter, so the tasks the signed-in analyst claimed are
  marked "Yours" instead.
- **Claim** on an open row claims the task for the signed-in analyst; the answer is said above the
  list and the queue renders again.
- **Keys** (optional, D-065): while a row has the focus (its link or its claim button), j and k
  move between the rows (one tab stop, a roving tabindex), Enter opens the task and ? lists the keys
  in a dialog; a key typed elsewhere on the page, into a form control or a dialog is not theirs, a
  key held down moves once, and Tab leaves the list. No key claims a task: claiming is the row's
  button.
- A later page whose read failed (the rulebook refuses a cursor from another filter) shows the
  refusal with a link back to the first page.
- A reviewer or an admin reads that review sampling, the queue's planned part
  (`admin.review-sampling`), waits for a route nobody has scheduled (D-039).

## Review workbench: `/admin/review/[taskId]`

One task, from `GET /v1/rulebook/review/tasks/{task_id}` and the reads it leads to: the facts (its
kind, status, regulator, priority, when it opened, who claimed it, the decision with its note, the
version with its status, high impact and closed), then three panes, side by side on a wide screen
and stacked on a narrow one, then what changed and the history. An id the rulebook does not hold is
the not-found page.

- **Source.** Each document the draft rests on (a candidate task's own document first), as the
  rulebook stores it: every clause with its page and anchor, each cited quote marked where its
  clause holds it word for word, the whole clause marked with the quote listed when it does not (a
  quote is verified by a match score); a link to the document viewer, and "Open the original file"
  (its type and size) to the stored-file handler in a new tab once the pipeline's record shows it
  stores one, else that it stores none. Nothing is framed (D-062). Then the draft's citations, each
  verified or not with its match score and when, linking its clause.
- **Candidate** (a candidate task). The outcome and confidence, the model and prompt version,
  whether the extraction asked for review, its status, the quotes the pipeline verified, the issues
  the checks found (code, clause, detail), whether it looks high impact and why, the rule key it
  suggests and whether a rule has it, and the draft it proposes field by field (the condition in
  words) with its quotes and each problem the rulebook found mapping it. An unparseable candidate
  says plainly that there is none, so the analyst drafts by hand.
- **Rule.** The draft in words (the rule and version, title, summary, where it applies, the period,
  how it recurs, the obligation, the condition, the open questions and the instrument), a link to
  the version's page, then the steps the task's state allows (D-061):
  - **Claim**: required before drafting or editing; claiming one's own task again changes nothing,
    and a task someone else claimed names them (read again after the rulebook's refusal). A claim,
    a draft or an edit that finds the task decided meanwhile is an error that names who decided it
    and says nothing was saved; only a decision that finds it decided is said as information.
  - **Draft from the candidate** (the claimant, before drafting): the rule key (the suggested one,
    another rule's, or a new rule's with its regulator and level), the proposed content with the
    analyst's changes, the citations (the candidate's quotes, or the analyst's own, each a clause of
    the document and a quote), the document's open relation candidates to take on (each row named
    by its candidate, however many the document holds, at most 50 ticked; each with the version it
    points at where its kind needs one, from the versions of the rule it names, or of every rule
    when it names none) and why. The action reads the open candidates and their versions again and
    refuses a candidate or a version the form would not offer, on its row, before anything is sent
    (D-061). Refusals are said plainly: a key no rule has or one a rule has, a rule of another
    regulator, a candidate drafted already (the page renders its draft), an overlapping version, a
    relation candidate gone or decided meanwhile, a target not aligned, a supersession cycle or a
    version the rulebook does not hold (each on the relation's row when the rulebook names it), a
    quote not in its clause, and an incomplete draft with every problem the rulebook listed.
  - **Edit the draft** (the claimant, while the version is a draft and not closed): the title,
    summary, dates, recurrence, obligation, open questions and condition (the predicate editor,
    D-064), only the fields changed sent; citations to add, each a clause of a cited document and
    its words, the row saying beforehand whether the clause holds them word for word; and why, for
    the audit. A content the rulebook refuses (`invariant-violation`) is said as such, each problem
    it found on a line of its own. A closed draft, a version under review and someone else's claim
    each say why there is no form.
  - **Decide**: approve (a reviewer's or an admin's; it submits a draft and approves it, after
    tagging it high impact when asked), return or reject with a note, a candidate's rejection with
    its reason, each confirmed in a dialog that says what the rulebook records. The round's
    approvals show as "k of required" with the approvers' ids ("you" for the signed-in one). The
    answer says the task after the decision, the version's status and approvers, the candidate's
    status and the rework's new task (linked), and stays on the page as it renders again; a second
    approval by the same reviewer is "a different reviewer must approve", a task decided before the
    decision arrived is read again and said with who decided it, reviews switched off on the
    rulebook and a wrong review token are said as such. An approved version is published from its
    own page (W5), which the pane links; the workbench publishes nothing.
- **What changed** (D-066): the candidate's proposal against the draft made of it, and the rule's
  previous version against the draft, field by field, a removed line "-" and an added one "+".
- **History**: the version's decision audit, newest first (each submission, return, approval,
  publication and edit, who, the move and the note), and every task the version or the candidate
  has had, oldest first, the current one marked and each other one linked.

With `web.admin_rulebook_writes` off or the review token unset, the page shows the task and says
which one holds the steps back.

## Review stats: `/admin/review/stats`

The queue in numbers, read-only and fresh on every visit: the tasks by status and by regulator, the
decisions (approved, returned, rejected), the rule candidates analysts decided (approved, approved
without an edit, rejected) with the acceptance rate explained as the share approved without an
edit (ADR-006's measure of the extraction; "None decided yet" while none is), the median time from
a task's opening to its decision and how long the oldest open task has waited.

## Decision review: `/admin/decisions`

The decisions the applicability engine could not settle by itself, one tenant at a time. The
review routes act for the tenant named in `x-tenant-id` (on these two routes a regulatory user
names the tenant reviewed), so the screen is a lookup like the notification console: a GET form
takes the tenant id and the status to list (open by default, resolved, every item), and the
engine's cursor pages on in the query string (D-051).

- Each item names the rule version it is about (from the rulebook, linked to its page), the node
  it was decided for, why it needs a person (a condition in words nobody judged, or a judgement
  below the review threshold) and when it opened; the decision under review with its result,
  confidence, trigger and profile version; and each condition of the rule as the engine judged it,
  with its outcome, confidence and reason.
- A resolved item says how it was settled (it applies, it does not apply, dismissed, or a later
  decision that needed no review), by whom, when, with the note and the decision it appended.
- A reviewer or an admin settles an open item: the result and a note (1 to 2000 characters), then
  a dialog that says what follows. Applies and does-not-apply append a decision with the reviewer
  as `resolved_by` (the session's user) and the obligation service makes or closes the
  obligations; dismiss closes the item and appends nothing. An analyst reads; a refusal (an item
  already settled) is shown with the engine's problem.
- Empty lists say why: nothing waits for a reviewer, nothing settled yet, or no item at all.

## Fan-outs: `/admin/fan-outs`

Every rule version's fan-out, newest first, 25 to a page by the engine's cursor: the version (its
rule key and number from the rulebook, linked to its run), the level, the status in words with
its last change (by whom and why), how many businesses of the level it decided and how many it
applies to, its flips against the version it supersedes, and when it started and last moved or
finished. Above the list, the global hold: while it is set, a danger banner names the reason, who
set it and when; an admin sets it or releases it through a dialog that asks for a reason (D-050).
Before any version is published to the engine the list says so.

## Fan-out control: `/admin/fan-outs/[ruleVersionId]`

One version's fan-out for the regulatory team, read-only for anyone but an admin (D-049):

- **The hold**, as on the list.
- **The run**: its status and what the status means, a progress bar of the businesses decided, the
  level, how many it applies to, the flips, the versions it supersedes (each opening its own run),
  when it started and last moved or finished, its last change, the publication event, and a failed
  run's error. A version with no run says why by its status: not published yet, or published with
  no run (the runbook's case of a worker that did not handle the publication).
- **Controls**, for an admin: pause and cancel ask for a reason (`ReasonDialog`; cancelling is
  destructive and says the decisions stay), resume takes one if given; only the controls the run's
  status allows are offered, and a finished run has none. The engine's refusal shows under them.
- **Roll back**, for an admin and a published version: the rulebook's withdraw through
  `server/api/rulebook-write.ts`, behind `web.publish_actions` and the review token, with the admin
  as the actor and a warning that says what follows (D-050). A version in any other status says
  only a published one can be rolled back.
- **The version**, from the rulebook: its name (linking to its page), title, status, period and
  publication, and for an admin a link to dry-run it in the impact explorer.

## Impact explorer: `/admin/impact`

The admin's dry run (D-049): a rule version in any status by its id (or named in the address,
`?rule_version_id=`), or a specification no version holds yet as the kernel's predicate tree in
JSON with the level it is decided at; every tenant's businesses or one tenant's; up to 50 sample
decisions. The form checks the shape first (an id, a JSON object, a level with a specification, a
UUID, a whole number) and keeps what was sent. The report says what ran over which businesses and
the financial year read, how many were in scope, decided and skipped, the counts by result and how
many would need review (each with its share of those decided), the attributes that decided the
results (each by key with the ontology's meaning), and the sample decisions with each condition's
outcome. A scope over the engine's maximum is its 422 `applicability-dry-run-too-large`, shown with
the way to narrow it; nothing is stored but the engine's audit entry.

## Prompts and model routes: `/admin/llm/prompts`, `/admin/llm/models`

The LLM gateway's prompt registry (each prompt by name and version with its owner, the eval cases
that guard it, flagged when there are none, the hash of its text to copy and what it is for) and
its routing table (each feature's primary and fallback model, the providers it may use or must
offer, the sort, the reasoning effort, the time limit, and whether the route is the default or set
by the gateway's environment, naming the `CW_LLM_ROUTES__<FEATURE>` variable it reads). Both are
read without a tenant header (the registries belong to no tenant) and cached five minutes under
`llm-gateway:prompts` and `llm-gateway:models`. Read-only: both pages say, from the planned registry
entry `admin.llm.edit-controls`, that edits wait for routes nobody has scheduled (D-056).

## Usage and budgets: `/admin/llm/usage`

Spend against the gateway's monthly budgets. By default the page shows every feature's budget for
this month (the gateway counts months in UTC), one read per feature; a GET form asks for one
tenant's budget (a feature then narrows its spend) or one feature's, for a month as `YYYY-MM`. Each
budget shows the spend and the ceiling in rupees to every place the ledger keeps (a spend of
`0.0012` is `Rs 0.0012`, never rounded to nothing), the share spent as a bar and a percentage
computed without floats, whether the gateway raised its alarm, and when the budget starts again. A
tenant's budget asked with a feature is labelled "Tenant budget, <feature> spend only", with a note
and "Spent on <feature>": the gateway sums that feature's spend alone against the tenant's whole
budget, and decides the alarm on that sum. The reads carry no tenant header: the usage route takes
its tenant from the header when the query names none, which would turn a feature's budget into the
internal tenant's spend (D-056). Read-only: the budgets are the gateway's settings.

## Profile review tasks: `/admin/profiles/review-tasks`

A lookup, like the notification console: the profile routes act for the tenant in `x-tenant-id`, so a
GET form takes a tenant id, a node id (a business's legal entity, a registration or a location) and a
financial year (this one by default), and the gateway is built with that tenant as
`ClientContext.tenantId`. The page shows the node (its level, key, name, profile version, a link that
looks up its parent, its id), its open review tasks (the attribute in the ontology's words, why the
task is open, the year, when it opened) and the snapshot the applicability engine evaluates for the
year, each value worded by the ontology (shown as stored when the ontology cannot be read). A node
the tenant does not hold is answered as such. Read-only: a task closes when the attribute is
answered on the business's own pages, and no route lists a tenant's tasks.

## Sources: `/admin/sources`

Every source the pipeline reads, read fresh: its name and key (opening its page), its adapter
type, regulator and site, the type it publishes and how many documents it holds, how it stands
(healthy, failing, fetching, paused) and whether the schedule may crawl it (enabled, disabled,
paused, or upload-only: a statute no site lists, which no crawl reads), its cadence, its freshness
(how long since a crawl listed it, in time and in cadences), its last listing, its latest run (a
backfill marked as one), its watermark and its last error. Counts above the table: the sources,
the failing ones, the late or stale ones and the upload-only ones.

Above them, the crawl switch as the web server can know it. The pipeline holds `pipeline.crawl` in
its own environment (`CW_PIPELINE_CRAWL_ENABLED`) and no route reads it, so the page shows the flag
as `packages/flags/registry.json` declares it (off by default), what off means (no source is crawled
on its schedule, "Fetch now" is refused without reading any site, uploads still work) and, as the
evidence, the schedule's latest crawl (the latest run with the trigger `schedule`), or that the
schedule has crawled nothing (D-058). An admin reads why the page offers no way to add a source:
the capability `admin.sources.add` is ready (the pipeline's `POST /v1/pipeline/sources` exists) and
not built.

## Source: `/admin/sources/[key]`

One source, its record taken from the list (the pipeline has no read of one source): its facts,
its adapter type's parameters, a page of its stored documents (keyset, 25 at a time, each opening
its page on the pipeline tool and its stored file in a new tab) and its latest ten crawl runs with
a link to every run of it on the pipeline page (not for an upload-only source, which has none). The
documents and the runs each have their own error state; a key the pipeline does not hold is the
not-found page.

For an admin (`admin.sources.write`, with the write token set; otherwise the page says which one is
missing):

- **Settings**: the name, the cadence, the enabled and paused switches and the parameters (as JSON,
  which the pipeline checks against the adapter type), with a reason of ten characters or more.
  The form posts the values it was rendered with beside the edited ones, and only the settings the
  admin changed from those are sent (`PATCH`): a setting someone else changed since, which this
  admin left alone, stands. A setting this admin changed that someone else changed since is
  refused by name with its value now, nothing is sent, and the page renders again so the form
  shows the source as it is (the fields start again whenever the page renders other settings). The
  dialog says what is recorded, and saving nothing says so without a request.
- **Fetch now**, for a source that lists documents: a crawl started at once (`POST .../fetch`,
  202 with its run and workflow), a paused source included. The panel says up front that while
  crawling is off the pipeline refuses, reads no site and records no run, and a refusal says
  exactly that rather than passing on a 503; a crawl already running, a source the pipeline cannot
  crawl and Temporal not answering are said plainly too.
- **Upload**, for an upload-only source: a PDF or an HTML page of at most the pipeline's limit
  (25 MB), what it is (the source's type unless one is chosen), its title, reference and
  publication date, and the reason. The form posts to the upload handler (below), which streams
  the file on; the answer links to the stored document, says whether these bytes were stored
  before, and says plainly when the document is stored but its ingest did not start (Temporal did
  not answer: uploading the same file again starts it, and nothing is stored twice). The page's
  documents are read again.

## Pipeline: `/admin/pipeline`

The pipeline's operations, one view at a time behind chips, each filtered by a GET form and paged
by the pipeline's cursor (25 a page), every filter in the address:

- **Crawl runs** (the default): every source's runs, the latest started first, of a source, a
  status and a trigger; each with when it started and ended, its source, why it ran (a backfill
  is marked as one: it lists part of history and leaves the watermark as it was), how it ended
  and its error, what its listing found (listed; stored, duplicates and failed) and its workflow.
- **Documents**: every source's stored documents, the latest first fetch first, of a status, a
  source, a type and publication dates (a date out of shape, or a range the wrong way round, is
  refused on its field); each with the type the pipeline reads it as, its classification (the
  route, the confidence and who decided: the detector, a person's triage or a person's type on a
  retry) and its rule extraction by the current prompt. A document opens its own page.
- **Dead outbox**: the rows the relay gave up on after eight failed sends, the newest dead first,
  of a topic (checked as the pipeline checks it); each with its topic and key, its attempts and
  last error, when it went dead and what it is about (never its body). An admin requeues one
  (`admin.pipeline.control`) with a reason in a dialog: the row goes back to pending and the relay
  sends it on its next pass; a row that is no longer dead is said as such.

## Stored document: `/admin/pipeline/documents/[documentId]`

One stored document: where it was listed or uploaded (by whom, for an upload), when it was first
fetched, its digest, size and type, its stored file (a link to the raw handler, below), its last
parse; how the pipeline reads it (its type, its classification with who decided it and why, its
extraction by the current prompt with its issues and whether it needs review); and the retries
people asked for, newest first, with their stage, type, reason, person and workflow. A malformed or
unknown id is the not-found page.

An admin retries it: from parse (its whole ingest again, without a new fetch), classify (the
detector reads it again; a person's decision stands) or extract (the rule extraction alone),
optionally read as a type a person gives (which reclassifies it and brings back a document set
aside), with a reason. The form carries the Idempotency-Key minted when the page rendered
(`pipeline.retry-document`), so sending the same request again (an answer that never came,
Temporal not answering) replays its attempt and records nothing twice. After such an answer the
page renders again with a new key, and the form keeps the first until an answer settles the
request (a success, or a refusal the same request cannot mend): pressing Retry again then starts
the attempt the pipeline recorded rather than a second one. Reloading the page gives a new key. The answers are said plainly: an ingest already running (wait for it), a triage task
holding it or nothing left to extract, a type no rule is extracted from, the key reused with another
retry, the key missing, and Temporal not answering ("send the same request again", with the button
that sends exactly it).

## Pipeline tasks: `/admin/pipeline/tasks`

The work people do on stored documents: manual parses (a document no parser reads, waiting for an
analyst to type it in) and triages (a document whose text names another type than its source
publishes), open ones first and oldest first, resolved and dismissed ones behind the chips, of a
kind. Each task names its document (its page and its stored file), why it opened and, once closed,
who closed it, when and why.

An admin resolves an open task with a reason: a manual parse with the transcript (typed as plain
text, one block per paragraph: a heading line marked `#`, a numbered paragraph, a table as rows of
cells; the page reads it as the pipeline will, counts its clauses and refuses what the pipeline
would before anything is sent), a triage with the decision (relevant and of a type, or not a
regulatory document). Either can be dismissed with a reason instead. The dialogs say what follows
(an ingest from the transcript, a document kept for reference, set aside or extracted). The same
resolution sent again is answered as the first was and said as done; a closed task, a resolution
that does not fit the task and an invalid transcript are said plainly.

## Stored files and uploads: `/api-bff/pipeline/...`

Two route handlers carry what a server action cannot: a document's bytes to the browser and a
file to the pipeline, each streamed rather than held whole (D-059). The proxy never sees them, so
each starts with the shared gate (`server/bff/gate.ts`) and its registry entry's roles.

- `GET /api-bff/pipeline/documents/[documentId]/raw` (`system.raw-document`): for a regulatory
  role (a visitor goes to sign in, a tenant role gets a 404), the document's record first (its
  content type and title), then its bytes from the raw store as they arrive, with the stored type
  (a PDF, an HTML page; anything else as `application/octet-stream`), `Content-Disposition`
  (inline for a PDF or an HTML page, an attachment otherwise; named by the id, with the title in
  `filename*`, well formed and at most 100 characters), `nosniff` and `private, no-store`. An HTML
  page is served under `sandbox; default-src 'none'`: its scripts do not run and it loads nothing.
  An unknown document, the role, a file missing or altered in the raw store and the raw store away
  are each a plain problem.
- `POST /api-bff/pipeline/sources/[key]/uploads` (`system.uploads`): for an admin only, from this
  site only (the gate's origin check, the sign-out handler's), with the write token set. It checks
  the key, that the body is a form with a file, the declared length, the file's type (a PDF or an
  HTML page, 415 otherwise) and the fields (the reason of 10 to 2000 characters, the title,
  reference, date and type, a 422 naming each), then sends the pipeline a new form (the session's
  user as `actor_id`, the checked fields, the file's bytes streamed through, counted against the
  limit) and answers the stored document or a plain problem. The limit is the pipeline's
  (`CW_PIPELINE_UPLOAD_MAX_BYTES`, mirrored as `CW_WEB_PIPELINE_UPLOAD_MAX_BYTES`, 25 MB by default)
  and the types are its own; `upload.test.ts` reads both from the service's code. A pipeline set
  lower refuses on its own, and the page shows its detail, which names its limit. A slow upload is
  never cut for its length: it stops only when no byte arrives for 30 seconds (nothing is stored),
  and the pipeline then has 60 seconds to answer.

## System: `/admin/system`

Every service as the web server reaches it: `GET /health` (up or down, the version, the time it
took, the reason it is down) and `GET /ready` (ready or not, each dependency check) of all ten,
probed in parallel from the server with two seconds each and no tenant header or token
(`server/health.ts`, the probe the admin home uses), so a stopped service is a row that says so
and never a failed page; a summary counts the services up and ready. From the screen registry,
each service's built screens and the routes screens still wait for from it, with who delivers
them. Then the web server's own facts: the environment, the sign-in provider, the build, Node.js,
the time limit of a service call, whether each rulebook token is set (never its value), the flag
provider, and OpenTelemetry as it registered when the server started (off, on with no exporter,
exporting, or failed; the flag is not read again; D-057). Refresh probes again.

## What waits

- The usage counts per attribute on the ontology browser: `GET /v1/profile/admin/attribute-usage`
  (services track, WP30), the waiting component `admin.ontology.usage`.
- Resending a failed notification: the hardened resend route (services track, WP30), the waiting
  capability `admin.notification.resend`.
- Reading another tenant once the services take the tenant from a bearer token: the console sends
  the looked-up tenant in `x-tenant-id`, which the notification service honours without a token
  today; with tokens it needs the admin reads the services track adds (WP30).
- The approvers of a review round on a fresh visit: the rulebook's version read does not carry them
  yet (the services track adds them to it), so the rule version page shows them from the answer
  to a step.
- Picking the entity for an alias by name: no route lists entities, so the decision takes the
  entity's id, which the canonical entities tool finds by name.
- Reading one relation candidate by its id: the page reads it through the list's keyset (D-055).
- Editing a prompt, a model route or a budget: no route exists; the prompt and route edits are the
  planned component `admin.llm.edit-controls`, and the budgets are the gateway's settings.
- Closing a profile review task from here, or listing a tenant's tasks: no route does either.
- The vector leg of the clause search: it needs a query embedding from the LLM gateway, which the
  page does not ask for.
- Browsing review items across tenants: no route lists the tenants with open items, so the
  decision review is a lookup by tenant.
- The admin's name in the engine's audit rows for a hold or a control: the engine reads no token
  in `header` mode and records the system until identity issues tokens.
- Adding a source: the pipeline's `POST /v1/pipeline/sources` exists, the form does not (the ready
  capability `admin.sources.add`); the e2e suite adds its synthetic sources through the route.
- Turning crawling on or off from a page: the switch is the pipeline's environment
  (`CW_PIPELINE_CRAWL_ENABLED`), which no route reads or sets.
- Review sampling, the planned part of the review queue (`admin.review-sampling`): no route exists.
- The review steps end to end on the UI-only stack: no route stages a version or a rule candidate
  of a spec's own there, so the e2e suite reads the queue, the stats and a seed task's workbench
  and opens the seed tasks, and the unit tests cover the claim, the draft, the edit with the
  predicate editor, the two approvals, the return, the rejection and the diff (D-063).
- Resolving and dismissing tasks and requeueing dead rows end to end on the UI-only stack: tasks
  open in the ingest and rows die in the relay, and the stack runs neither (no Temporal, no relay),
  so the e2e suite reads their empty states and the unit tests cover the writes (D-060).
