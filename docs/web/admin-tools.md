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
template, rulebook, decision review, fan-out and impact pages each have a sibling `loading.tsx`
with a skeleton (the console's sits in the route group `(console)`, the rule version list's and
the fan-out list's in `(list)` and the resolve tool's in `(resolve)`, so each wraps that page
alone, as the home's sits in `(home)`); under one, a
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
| Decision review     | `/admin/decisions`                       | every regulatory role reads; a reviewer or an admin settles | `GET /v1/applicability-engine/review-items`, `POST .../{item_id}/resolve`, for the tenant looked up; each version from the rulebook |
| Fan-outs            | `/admin/fan-outs`                        | every regulatory role reads; an admin holds | `GET /v1/applicability-engine/fan-outs`, `GET` and `PUT .../fan-out-hold`; each version from the rulebook |
| Fan-out control     | `/admin/fan-outs/[ruleVersionId]`        | every regulatory role reads; an admin controls | the run, the hold, `POST .../fan-outs/{id}/pause`, `/resume`, `/cancel`; the version and its withdraw (`server/api/rulebook-write.ts`, `web.publish_actions`) |
| Impact explorer     | `/admin/impact`                          | `admin`                 | `POST /v1/applicability-engine/dry-runs`; the ontology for the attributes |

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
  return a version in review, publish or return an approved one, withdraw a published one. Each
  opens a dialog that says what the rulebook records; return and withdraw ask for a reason of ten
  characters or more (`ReasonDialog`), the others take an optional note (`ConfirmDialog`). The
  acting analyst is the session's user, filled in by `server/api/rulebook-write.ts`, never a form
  field, and an approval is never sent as synthetic. The panel says what the step did and lists the
  round's approvers from the rulebook's answer ("1 of 2 approvals in this round. It needs a second
  approver: a different analyst.", the signed-in analyst named); every refusal (the same analyst
  approving twice, citations missing or unverified, an overlap, a relation that cannot take effect,
  publishing turned off) is shown under the step with the rulebook's title, detail and correlation
  id. On success the page renders again in the new status.
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
- Creating an entity: only an analyst's decision on the entity review queue does it, and those
  screens are not built, so on a fresh stack every name resolves to not found, unqualified or empty.
- The vector leg of the clause search: it needs a query embedding from the LLM gateway, which the
  page does not ask for.
- Browsing review items across tenants: no route lists the tenants with open items, so the
  decision review is a lookup by tenant.
- The admin's name in the engine's audit rows for a hold or a control: the engine reads no token
  in `header` mode and records the system until identity issues tokens.
