# Obligation pages

What a business has to do and why: the obligation list and the calendar, one obligation's page
with its tracking, the changes feed, and asking a question. They are the registry entries
`owner.obligations`, `owner.calendar`, `owner.obligation`, `owner.changes` and `owner.ask`, tabs
of a business's pages (`/b/[businessId]/...`, [business-pages.md](business-pages.md)), readable
by every tenant member role in a business or CA-firm tenant. A CA firm's people also have the
clients a change affects, with the bulk change card (`ca.change-impact`, below).
[product-loop.md](product-loop.md) follows a rule from its publication to these pages. The onboarding summary
(`owner.onboarding.done`) waits for the business's first obligation. Every page ends with the
"not legal advice" footer (section 2 of the terms) and says nothing a service did not say.

The calls are typed from the committed specs: the obligation service (the public list of a node,
one obligation and its tracking writes), the profile service (the business and its nodes), the
applicability engine (a node's decisions, a change's impact), the rulebook (the changes feed, a
cited clause or document) and qa (the public ask). Tenant reads are never cached; a clause and a
document are the same for every tenant and kept five minutes under their tag
([data-layer.md](data-layer.md)).

## Which nodes

The obligation service keeps an obligation for the profile node it is about: a GSTIN's returns for
its registration, an entity's own duties for the entity. A business's pages therefore ask the
entity and each registration `GET /v1/businesses/{business_id}` lists, and merge what they answer.
The profile service has no route that lists a registration's locations yet, so an obligation kept
for a location does not appear on these pages until it does.

## The list: `/b/[businessId]/obligations`

The obligations by due date (the ones without one last, then by id, the service's own order), 25
to a page, each with its period, the GSTIN it is kept for (when the business has several nodes),
its status, the due date in India with how it relates to today ("Due in 3 days", "Overdue by 2
days" in words, never colour alone), whether its rule has been reviewed and how many verified
citations it has, and the engine's latest decision of its rule for its node as a badge ("Applies",
"Not sure, needs review"; "Not decided" for a node the engine has no decision for, "Not known now"
when the read failed, without failing the list), read once per node and rule version on the page
(D-053). The title opens the obligation.

- **Filters** are a GET form, so the choice is in the address: a status (every status, still to
  do, or one status; the service's repeated `status`) and a due window, "Due from" and "Due by",
  days in India with both ends included. The service lists a window of at most 366 days; the form
  says so up front, and a longer window (or an end before its start, or a date that is not one)
  is refused on its field with the number of days, and nothing is listed for it. The window is
  never shortened behind the person's back. With a window, obligations without a due date are
  left out, as the service does.
- **Paging** follows a key, not a page number: each node's list has its own cursor, which a merged
  page cannot carry for every node in the address, so the next page's address carries the key of
  the last row shown (`after`, the due instant and the id). The next page asks each node again
  from that row's due day (`due_from`) and drops the rows up to the key; a node that would need
  more than five requests to get past the key is reported rather than guessed. "Back to the first
  page" returns to the start; there is no "previous page". A list read while obligations change
  may show a row on two pages or skip one, like any keyset list.
- **Empty** says why: nothing worked out yet (the engine decides each published rule against the
  answers, and the obligation service makes the obligations of the rules that apply), nothing
  matching the filter, or the end of the list.

## The calendar: `/b/[businessId]/calendar`

One month (`?month=2026-10`, this month in India by default) as the UI kit's month grid
(`role="grid"`: arrow keys move by day and week, Home and End within the week, Page Up and Page
Down by month, Enter or Space selects). Each due day shows its count, read with the date as "2
obligations due"; the chosen day's obligations are listed below the grid with links to their
pages. The month is the due window of the read, every node's whole month. Moving to another month
in the grid reads it through a server action, so the grid keeps its place (focus stays on the day
the keyboard reached) while the page says it is loading, and `history.replaceState` puts the month
in the address for a reload or a shared link; the previous and next months are also plain links.

## One obligation: `/b/[businessId]/obligations/[obligationId]`

`GET /v1/obligation/obligations/{id}` gives the obligation with what the obligation service keeps
of its rule version, the verified citations, the history and the comments. An obligation of
another business of the tenant, an unknown id or a malformed one is the not-found page.

- **The facts**: status, due date in India and how it relates to today, when and why it closed,
  the GSTIN or PAN it is for, the evidence it needs, who it is given to.
- **What to do**: the rule's steps, in order.
- **The rule**: its title and dates (the end is exclusive, so the last day shown is the day
  before); a "not yet reviewed" warning while the seed rule's status is `needs_review`, whatever
  approved its publication; and the reviewed-by line, the approvers of the round it was published
  from (user ids; no route names them) with the publication date. The local product's demo
  publication shows both: two synthetic approvers and the warning, because a synthetic approval
  reviews nothing.
- **What the rule cites**: each verified quote as stored, the whole clause on request and the
  regulator's source document, read with `GET /v1/rulebook/clauses/{id}` (only an http or https
  address becomes a link). A clause that cannot be read leaves its quote, with a note.
- **Why this applies**: the engine's latest decision of the rule version for the obligation's
  node (`GET /v1/applicability-engine/businesses/{node}/decisions?rule_version_id=&limit=1`): the
  result, the confidence, when it was decided, the financial year it read, and each condition of
  the rule in the engine's words with its outcome, confidence and reason. A decision taken since
  the obligation was made is said to be later; one that needs a reviewer says so; no decision, or
  an engine that did not answer, is said in place (with the correlation id) without failing the
  page.
- **Status**: start an open obligation, complete or waive one still to do (`POST .../status`).
  Starting needs no confirmation; completing closes it for good, so a dialog says so first;
  waiving asks for the reason the history and the audit keep (at least ten characters, the
  service's rule, checked in the dialog and again in the action). A closed obligation takes
  comments but no other change; a write to one comes back as the service's 409.
- **Who it is given to** (`PUT .../assignee`): the identity service lists a tenant's users to its
  admins only (owners and CA admins), so for them the page offers the tenant's active users by
  name (`GET /v1/identity/users`; no contact detail is shown). Anyone else, and an admin while
  identity cannot list them (it answers a signed-in admin's token, which the web session does not
  carry yet in token mode), gives the obligation to themselves ("Give it to me" sends the
  session's user id, never one from the form), to nobody, or to a user by id; the page says why.
  With a verified token the obligation service checks that the user belongs to the tenant; without
  one it keeps the id as named.
- **Comments** (`POST .../comments`): 1 to 2000 characters, kept for good, oldest first; the
  author is "You" or the role the service labels them with, never a name.
- **History**: every change, oldest first, worded ("Due date moved from ... to ...", "Closed:
  Waived", by you, by a user, or by the system), with a waiver's reason.

Every write carries the Idempotency-Key minted for that form's render (one per form). A double
submit, or a retry after a lost answer, gets the service's first answer back with
`Idempotent-Replayed: true`, and the page says the request had already been recorded. If no
answer arrives at all (a dropped connection), the form keeps the request whole, key included, and
"Try again" sends exactly it: recorded at most once either way. After a write the obligation, the
list and the calendar render again, and the forms get new keys.

## Changes: `/b/[businessId]/changes`

The rulebook's published changes, newest first, 20 to a page by the service's cursor ("Older
changes", "Back to the newest changes"): a version published, superseded or withdrawn, or a due
date moved. Each card gives the kind, the rule's title and summary, the version and regulator,
when it changed, the version's dates, the due date it moved (with the period), the versions it acts
on, the not-yet-reviewed warning while its seed status is `needs_review`, the approvers of the
round it was published from, and its citations with the clauses' text.

Whether a change applies to this business comes from `GET /v1/changes/{rule_version_id}/impact`,
read once per version on the page: the tenant's businesses with their latest decision of the
version, grouped under their client (the legal entity). The page finds this business's group,
walking the impact's pages of 200 clients until it does (a CA firm may have many; past five pages
it says it could not get there), and says "Applies to this business" when the version applies to
any of its nodes, "Not sure" when the engine is unsure for one and sure for none, "Does not apply"
when every node decided says so, and "Not decided for this business" when the engine has no
decision of the version for it (a business made after the version's fan-out, for one). Each node's
decision is listed with its date. An impact that could not be read is said on its card with the
correlation id.

For a CA firm's people, each card links to every client the change affects (below).

## Affected clients: `/changes/[ruleVersionId]/impact`

A CA firm's admin and staff (`ca.change-impact`; a business tenant is sent to `/forbidden`) read
what a change means for every client of the firm, from `GET /v1/changes/{id}/impact` (D-052):

- The change from the rulebook (its rule key, number, title and status; an id the rulebook does
  not hold is the not-found page), the counts over every business of the firm with a decision of
  it, and how far its fan-out got over every tenant.
- The clients, 50 to a page by the engine's cursor: the affected ones by default, or the unsure,
  the not affected or every one by a filter in the address. Each client is named from the profile
  service with its PAN; each of its businesses (a GSTIN, or the client itself by its PAN) shows the
  engine's latest result as a badge, how sure it was and when it decided. Every filter's empty list
  says why.
- **The bulk change card**: one card to each affected client's own people who follow it (an owner
  or staff; the firm's own people hear in their daily digest), about the client's first open
  obligation of the change, through the usual queue, quiet hours and batching. The page renders
  the affected businesses (walked from the impact, at most 500) into the form with the
  Idempotency-Key it minted, so sending again from the page, or "Try again" after an answer that
  never arrived, is the same request and the service answers with its first answer, which the
  page says. The answer lists each business: queued (people told now), already told, nobody to
  tell, or not affected (no open obligation of the change). With the notification service's
  switch off the page says nothing was sent, with the service's problem.

## Ask: `/b/[businessId]/ask`

Behind `web.qa_enabled` (off by default; the override counts in local and test only): while it is
off for the tenant the Ask tab is hidden and the page says so without a form, and the action
refuses. The question (1 to 1000 characters) and the node it is about travel in the POST body to
`POST /v1/qa`, never in an address; the nodes offered are the registrations first, since a
GSTIN's returns are kept for its registration, then the business.

The answer shows its outcome and the layer that decided ("Answered from this business's
obligations", "from the knowledge graph", "from a search of the clauses in force"), the service's
text as given, the date it is about, its citations with each clause read from its document (`GET
/v1/rulebook/documents/{id}`, by the citation's clause reference) and the source to check, and
every layer that ran with what it did. A question that is not covered says so with the service's
fixed sentence and why, never a guess; a refusal (the node unknown to the tenant, the model budget
used up, a service down) comes back as the service's problem with its correlation id, and the
question stays in its field.

## The first obligation after onboarding

`/onboarding/[businessId]/done` asks whether the business has its first obligation yet. Working
out what applies happens after the answers are stored (the profile change reaches the engine,
which decides each published rule, and the obligation service makes the obligations), so the
page reads it once when it renders and then checks every 3 seconds through a server action (one
row of each node's list), saying so while it does. It stops at the first obligation, linking to
it with its due date, or after 90 seconds with an honest note: the work goes on in the background
and can take longer, or no published rule applies to the answers so far; "Check again" starts
over. A failed check is shown with its correlation id and the checks go on. On `make web-stack`,
which runs no worker, nothing ever appears; on `make product` the first obligation arrives within
seconds.

## What waits

- A registration's locations: a profile route that lists them.
- Evidence for an obligation (`owner.evidence`, planned) and reporting an error in one
  (`owner.report-error`, waiting on the services track's WP24 routes).
- Feedback on an answer (`owner.answer-feedback`, planned).
- The approvers by name: a route that names users of the internal tenant.
- Telling more than 500 affected businesses of one change: the bulk card names the first 500 and
  the page says so.
