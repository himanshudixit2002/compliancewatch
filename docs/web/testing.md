# Testing

Two levels. Unit tests (vitest, jsdom, Testing Library) cover everything that can render or run
without a request scope: components, view models, mappers, config, helpers, server modules
called directly. The Playwright suite covers what unit tests cannot: the route files (a
`page.tsx` is an async server component that needs a request), the shells with real
navigation, the built app's headers and status codes, and page-level accessibility. Both levels
run axe. No test uses a mock service, and no e2e test uses a mock of anything: the suite signs
in through the real sign-in form on the fake provider where a page needs a session, and the
pages that read a service read the real ones, started by `make web-stack` and seeded by `make
web-seed` before the suite (`make web-e2e` points the app at the stack's ports).

## Unit tests

`apps/web` and `packages/ui` each run `vitest run --coverage` (`pnpm --filter web test`,
`pnpm --filter @compliancewatch/ui test`; `test:watch` for the watcher). Tests live next to the
file as `<name>.test.ts` or `.test.tsx` with sentence names in the present tense.

**Setup** (`apps/web/src/test/setup.ts`): the `toHaveNoViolations` matcher from
`@compliancewatch/ui/test/axe` is registered on `expect`; `server-only` is mocked to an empty
module so server modules can be imported by a test; `next/navigation` is mocked (`redirect`,
`notFound`, `usePathname` returning `/`, `useSearchParams`, `useParams`, `useRouter`) because
those need a request scope. A test that needs different behaviour changes the mock for that test.
`@testing-library/react`'s `cleanup` runs after each test. `packages/ui/src/test/setup.ts` does
the same without the Next mocks.

**The axe matcher** (`packages/ui/src/test/axe.ts`) is written over `axe-core`, which was already
in the workspace: `runAxe(container)` runs axe with the `region` rule off (a component rendered
on its own has no landmarks) and `color-contrast` off (jsdom has no layout to measure it; the
Playwright suite and `contrast.test.ts` cover colour), and `toHaveNoViolations()` formats the
violations with their targets. Every component test and every feature view test ends with it.
The check stays component sized: a view that renders the whole registry or the whole catalogue
(the sitemap, the admin tool list, `/design`) runs it on one section's table or group, because
axe over a page-sized jsdom tree takes tens of seconds on a CI runner; the Playwright suite runs
`AxeBuilder` over those pages in full. No unit test sets its own timeout; the configured 30 s
ceiling applies.

**Synthetic fixtures.** Test data reads as invented at a glance: "Example ..." text (`Example
return 1`, `Example notice 1`, `Example regulator`, `Example owner`), dates in the year 2000,
zero or example identifiers (`00000000-0000-4000-8000-...`), `example.com` addresses and numbers
such as `+910000000001`. A fixture that names a real return, regulator, business or person can be
taken for a statement about the rules, and it goes stale when they change.
`src/test/synthetic-fixtures.test.ts` reads every test (`*.test.ts(x)`, `*.test.mts`, `*.spec.ts`)
and every fixture (a file whose name holds `fixture`, or any file under a `fixtures/` folder) in
`apps/web/src`, `apps/web/e2e`, `apps/web/scripts` and `packages/ui/src`, and fails on the
realistic tokens, in any case and at the start of a word: CBIC, GSTR (so GSTR-1 and GSTR-3B), CGST,
IGST, SGST, Acme and Asha. Exempt: the recorded rulebook fixtures under
`apps/web/scripts/seed/fixtures`, which were recorded from a real notification and which the seed
replays and hashes byte for byte (there are no recorded e2e fixtures; the specs read what the seed
wrote at run time). Allowed, each with its reason in the test: the guard itself and the design
catalogue's `fixtures.test.ts`, which name the tokens in order to reject them, and the product
journeys (`e2e/product/journey-product.spec.ts` and `journey-oversight.spec.ts`), which ask the
seeded product the question `cw-product check` asks and find the seed calendar's annual return's
change and fan-out by its rule key (D-047). A
new test uses the example forms above; a live page whose test seems to need a realistic token
gets synthetic data instead, or one narrow entry in the allow list with the reason.

**Coverage.** Both packages hold 80% for lines, functions, branches and statements. In `apps/web`
the route files (`page.tsx`, `layout.tsx`, `loading.tsx`, `error.tsx`, `not-found.tsx`,
`global-error.tsx`, `route.ts`), `instrumentation.ts`, `proxy.ts` and `src/shared/generated/**`
are excluded: they are thin and exercised by the Playwright suite. `scripts/` and `e2e/` are
outside `src` and outside the floor.

**What each kind of file is tested for:**

| Code                             | Test                                                                                                                                       |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `packages/ui` component          | renders, props and variants, keyboard behaviour with `user-event`, axe                                                                     |
| `features/*/ui` view             | renders the view model, links and text, axe; the design catalogue additionally rejects the regulatory vocabulary                            |
| `features/*/model`, `entities`   | pure functions: inputs to outputs, edge cases                                                                                              |
| `shared/config/screens.ts`       | the status rules against the committed OpenAPI specs, route coverage both ways, unique ids and routes, `matchScreen`, `hrefFor`, visibility |
| `shared/config` (roles, flags)   | set membership, `can()`, the flag declaration shape                                                                                        |
| `shared/i18n`                    | every `t("...")` literal in `src` exists in `en.json`, and every key in `en.json` is referenced in `src`: as a literal, or as a member of one of the dynamic families the test lists (a template literal such as `` t(`status.${status}`) `` builds the key; each family names its module, and a family no template literal needs fails); interpolation; the key-by-key fallback |
| `shared/lib`                     | IST rendering, financial-year labels, decimal money, identifiers, `safeNext`                                                               |
| `server/legal.ts`                | version and title extraction, that no file in `docs/legal` contains a raw HTML tag (marked does not sanitise), and the onboarding gate: closed in prod while the terms or the privacy notice is a draft, open in local, test and staging |
| `server/required-consents.ts`    | the required purposes granted at the current versions (missing, withdrawn and older grants refused), the read's subject, tenant header and no-store, a problem passed on; `createBusiness` makes no profile call without them |
| `server/api/rulebook-write.ts`   | the role, the flag and the review token checked in that order (a refused port answers every decision, citation and step without a request), each token sent only by its own client and never in an error, `decided_by` and `actor_id` from the session, no `synthetic` in an approval, the decision, citation and step bodies and answers mapped, a guard of the publish flow passed on with its problem, the rulebook's token problems reworded to name the variable to set |
| `server/telemetry.ts`, `telemetry-redaction.ts` | the plan per flag and endpoint, the outcome kept on `globalThis` for the system page (a later flag change does not show), the redacting processor ahead of the exporting ones; a span from the real SDK redacted at the start and at the end (name, attributes, events, status): no query, the preference's recipient and any email, phone number, PAN or GSTIN replaced (synthetic values), ids and route templates kept |
| `server/session.ts`, `dal.ts`    | the cookie round trip (tamper, expiry, wrong key, wrong shape), the cookie attributes per environment, each gate's redirect or 404 (the cookie store from `src/test/fake-cookies.ts`) |
| `server/auth/*`                  | `providerFor` per variable value; the fake adapter's validation, stable user id, second-factor assertion and refusal outside local and test |
| `features/auth`                  | the form (roles per kind, the busy state, the errors it shows) with a fake action; the action's cookie and redirect; the seed-state reader |
| `src/proxy.ts`                   | the matcher through `next/experimental/testing/server` and the pass-or-redirect decision for every registry page (excluded from the coverage floor) |
| `src/test/architecture.test.ts`  | the layer rules over the real tree; the parked folder map: every feature folder no route file imports is parked for registry screens that exist and are not live, and a folder a page imports leaves the map ([architecture.md](architecture.md), "Parked feature folders") |
| `src/test/handler-gate.test.ts`  | every `route.ts` under `app/api-bff/` exports its methods as functions whose first statements await `gateHandler` from `server/bff/gate.ts` with the handler's own request and the registry entry of the file's route, and return its refusal; anything else fails naming the file (D-059) |
| `server/bff/gate.ts`             | the origin of a write before the session, a reader without a session sent to sign in and back and a writer answered 401, a tenant role's 404 for a regulatory tool, a short role's 403 naming the entry's roles, a tenant kind the entry does not list |
| `src/test/synthetic-fixtures.test.ts` | no realistic token in a test or a fixture of the web app or the UI kit ("Synthetic fixtures" above) |
| `src/test/screens-doc.test.ts`   | `docs/web/screens.md` equals the generator's output; the awaits audit                                                                      |
| `packages/ui` tokens             | `contrast.test.ts` (4.5:1 text, 3:1 UI, both schemes), `tokens.test.ts` (the two dark blocks agree), `tokens.build.test.ts` (the utilities compile) |
| `packages/ui/src/imports.test.ts`| internal imports are relative, never `@/` or the package name                                                                              |

## End-to-end tests

`apps/web/playwright.config.ts` runs the specs in `apps/web/e2e` against `next start` on `PORT`
(3000 unless set) with `CW_WEB_ENV=test`, `CW_WEB_AUTH_PROVIDER=fake` and a fixed session
secret (32 bytes of `e2e`; it keys the cookies of one run and is not a secret), chromium only,
and waits for `/api/health` before the first test. It has three projects: `chromium`, every spec
but `e2e/product`, against the memory stack (`make web-e2e` and the `web-e2e` job run it with
`--project=chromium`); `stack-guard`, which `chromium` depends on and so runs first (below,
"Never against the shared database"); and `product`, the real-data journeys against `make product`
(below), which depends on nothing. The config turns `web.publish_actions`, `web.admin_rulebook_writes` and `web.qa_enabled` on for the
run. Outside CI it reuses a
server already listening on that port. On CI it retries once and writes the HTML report.
`e2e/fixtures.ts` extends `test` with `checkA11y(selector?)`, which runs `AxeBuilder` on the page
(or one selector) and fails on any finding of impact `serious` or `critical` (moderate and minor
findings are the unit level's business), and with `signIn(persona)`: the personas (`OWNER`,
`COMPLIANCE_LEAD`, `CA_ADMIN`, `ANALYST`, `REVIEWER`, `ADMIN`) are signed in once per worker through the
fake form and their cookies are added to the test's context, so a spec that needs a session
starts with `await signIn(ANALYST)`; `signInThroughForm(page, persona, next?)` drives the form
itself for the specs that test it. `e2e/rulebook-helpers.ts` holds the rulebook reads the
rulebook specs compare the pages with (the rules in key order, a rule's versions, the recorded
notification with its id and clause ids); every decision those specs make goes through the pages.
Its one write, `stageReview(forms, relations)`, registers a synthetic document of one clause
through the pipeline's routes (the write token, as the seed sends it), with a form mention per
review group and the relation candidates asked, each named for the run (`EX-<nine digits>`), so the
review specs decide what no other run or spec touches.
`e2e/pipeline-helpers.ts` does the same for the pipeline: reads to compare the source and pipeline
pages with (`pipelineGet`, `sources`), and staging through the pipeline's routes with the write
token: `stageUploadSource()` adds a synthetic upload-only source for the test (`example_<nine
digits>`, no site, statutes), `stageUpload(key, title, file?)` uploads synthetic bytes to it
(`syntheticPdf` or `syntheticHtml`, each different every time, with the id the pipeline will give
them), which the stack stores and answers 503 for (no Temporal), and `crawlIsOff()` asks the
pipeline whether crawling is off the way `cw-product check` does, before any spec fetches a built-in
source (D-060). `e2e/review-helpers.ts` reads the rulebook's review queue, a task and the stats for
the review specs to compare with, and presses "Open seed tasks" through the queue page; it stages
nothing else, since the stack has no route that makes a review task of a spec's own (D-063).

The specs on `main`:

| Spec                     | Covers                                                                                                                                                    |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `a11y.spec.ts`           | every page in the registry except the catch-alls and the live pages with route parameters (a legal document, a business: `example` is a 404 there, so their own specs visit them with real ones and run axe), grouped by the first persona its roles and tenant kinds admit (public pages without a session): live pages by their route, planned, waiting and ready pages through the catch-all with `example` for each parameter; one h1, status 200, the notice on non-live pages, axe |
| `home.spec.ts`           | the landing links, the skip link moving focus to `main`, the sign-in link leading to the form                                                              |
| `sign-in.spec.ts`        | the redirect with `next` from a gated page, the server's field errors, a refused submit keeping every value and focusing the errors, an owner signing in, returning to `/account`, the account menu and signing out, the role homes (`/businesses`, `/admin`), a signed-in visit to `/sign-in`, the last seeded tenant offered by the form and signed into (needs the seed), the roles following the tenant kind, `/sign-out` as POST only with the origin check, signing in and out through `127.0.0.1` (a host other than the one `next start` binds) |
| `account.spec.ts`        | the session facts in IST, the copy controls, the note on `/me`, the header name linking to `/account`                                                     |
| `admin-gate.spec.ts`     | anonymous `/admin` to sign-in with `next`; a 404 without any admin markup for an owner and a compliance lead on every admin path; an analyst opening the tools without the admin-only entries and a 404 on one of them; a reviewer and an admin opening the tools; an unknown admin path as a 404 inside the admin shell with the way back (axe) |
| `sitemap.spec.ts`        | one table per section, a waiting tool's awaited route and owner, a ready tool's chip, a built tool's chip, the link to its notice                         |
| `legal.spec.ts`          | each listed document under the draft banner with its `-draft` version; an unlisted document is a 404; printed (print media, light and dark schemes): no shell, the banner kept, the paper line, black text on white |
| `design.spec.ts`         | every catalogue section with axe, the theme control, dialogs (focus, Escape, the ten-character reason), the calendar keys                                   |
| `admin-home.spec.ts`     | as an analyst: the tool list with status (waiting, ready and available) and service READMEs, the environment banner, sidebar navigation marking the current tool, the "Not built" and "Waiting" hints of tools not built yet as their links' descriptions (in an admin's sidebar, which holds a tool not built yet); against the stack (needs the seed): a number and no error in each count tile, the open mentions, every service answering its health check (axe); the counts are not compared with numbers, since other specs change the queues |
| `admin-entity-review.spec.ts` | the entity review queue and a group's page: a tenant role gets a 404; a group address without a group or with an unknown type says so (axe); against the stack (needs the seed): an analyst opens the queue from the sidebar and filters it to sections, the recorded notification's groups, compared with the rulebook's list; a reviewer opens a group from the queue, its mentions compared with the rulebook's, and one mention marked in its document; an analyst rejects a group staged for the run with a reason (the dialog, the answer, the empty state, nothing left open on the rulebook) and makes the entity of another, opening the entity the rulebook resolves the name to; axe on each state |
| `admin-relation-review.spec.ts` | the relation candidate queue and a candidate's page: a tenant role gets a 404, a malformed id the not-found page; against the stack (needs the seed): an id no status holds is the not-found page; an analyst opens the queue from the sidebar, narrows it to the recorded notification (its open candidates compared with the rulebook's) and its rejected ones; a reviewer opens the recorded candidate (the quote marked in its clause, the target rule's versions and an open draft offered); an analyst rejects a candidate staged for the run with a reason, and approves another from a draft no other spec moves onto the next rule's draft, the rule relation read back from the rulebook and the graph opened; axe on each state |
| `admin-review.spec.ts` | the review queue against the rulebook the stack starts with the seed calendar's drafts (needs the seed): an analyst opens the seed tasks twice (either answer each time, since other specs decide tasks meanwhile; the first rule's draft keeps exactly one task waiting), reads the open tasks in the rulebook's order (each row's link, version, approvals, claim offered and never pressed), filters by every status, by seed drafts and by a regulator the stats count (each page compared with the rulebook's queue read either side of it, read again while they differ), compares the strip with the stats read either side of the page, and drives the keys: nothing happens for a key outside the list, ? from a row lists them, a held j moves one row, k moves back and Enter opens a task, the keys left to the dialog; a reviewer reads what review sampling waits for; axe on each state. This spec claims and decides nothing (D-063) |
| `admin-review-workbench.spec.ts` | a seed task's workbench, read-only (needs the seed), on the last rule in key order, which no other spec moves: the title, the facts and the version's link compared with the rulebook's task read, the source pane (the empty state, or the cited documents and citations), the draft in words, the claim offered and not pressed, the edit form held back until a claim, an analyst's approval refused in words, return and reject waiting for a note, the approvals as "k of required", no earlier version to compare with and the task in the history; a reviewer offered the approval with the high-impact tag, the dialog opened and cancelled with the task still open; the original file opened in a new tab (`rel="noopener"`, no frame) when a draft cites a document (skipped when none does); an unknown id is the not-found page; axe on each |
| `admin-review-stats.spec.ts` | the review stats (needs the seed): every count by status, regulator, decision and candidate, the acceptance rate and the time compared with the rulebook's stats read either side of the page; the way back to the queue; axe |
| `admin-rulebook-rules.spec.ts` | the rule list: a tenant role gets a 404; against the stack, an analyst opens it from the sidebar, finds every rule the rulebook lists in key order, filters by a key and opens that rule's versions (axe) |
| `admin-llm.spec.ts`      | the LLM gateway pages: a tenant role gets a 404 for each; against the stack, the prompts and the model routes compared with the gateway's (the edit note naming the routes it waits for), every feature's budget for this month compared with the gateway's (the spend by its shape, since other specs ask questions the gateway counts), the seeded tenant's budget, and a malformed month refused on its field; axe on each |
| `admin-profile-review-tasks.spec.ts` | the review task lookup: a tenant role gets a 404, a malformed lookup is refused on its fields with what was typed kept (axe); against the stack (needs the seed), an analyst opens it from the sidebar and looks up the seeded registration (its key, its open tasks and its snapshot's attributes compared with the profile service's, axe), follows its parent to the legal entity, and an id the tenant does not hold is answered as such |
| `admin-system.spec.ts`   | the system page: a tenant role gets a 404; against the stack, an analyst opens it from the sidebar and finds all ten services up and ready, each with the version its own /health reports and the address probed, the registry's screens per service, the web server's facts (the environment, OpenTelemetry off), and the page again after Refresh (axe) |
| `admin-rulebook-documents.spec.ts` | a tenant role getting a 404 for the tool and the viewer; a malformed id as a real 404 inside the admin shell; against the recorded notification the seed registers (needs the seed): opened from its sha256 through the form (the current sidebar link, axe), the title, the reference in the breadcrumbs, every clause with its anchor and page, the id; an unknown id answered on the field (focused, value kept) and a 404 on the viewer; a jump to a clause (the address fragment, focus on the clause); a mention's span marked from a link with the clause ids read from the rulebook (the note, focus, axe), the whole clause when the span runs past it, a clause the document does not hold, a malformed link. Read-only, so it runs in parallel and again on the same stack |
| `admin-flags.spec.ts`    | the flag console as an analyst, opened from the sidebar: every flag of `packages/flags/registry.json` with its description, owner, expiry date and a string flag's default, an answer (on or off) for each flag the web app reads and the services that read every other one, no control that changes a flag (axe); a tenant role gets a 404 |
| `admin-ontology.spec.ts` | the ontology browser as an analyst, opened from the sidebar, against the profile service (needs the stack): the version, a heading per level, every attribute in its level's table with its question (or "Not asked") and its value labels as `GET /v1/ontology` returns them, the note naming the usage route it waits for (axe); a tenant role gets a 404 |
| `admin-notifications.spec.ts` | the notification console against the notification service (needs the seed): an analyst opens it from the sidebar, is refused a malformed tenant id on its field (the business id kept), looks up the seeded tenant and business, finds the opt-in confirmation compared with the service's record (template, state, the address masked), opens it (the tenant, the business and obligation ids, no resend note for an analyst, axe) and goes back; an admin opens a notification by its id, is asked for its tenant, and sees what resending waits for (the route and its Idempotency-Key, no resend button); an unknown id is the not-found page; a reviewer reads the message templates as the service lists them (axe) and gets the not-found page for the console; a tenant role gets a 404 |
| `admin-rulebook-versions.spec.ts` | the rule version list and a version's page against the rulebook the stack starts with the seed calendar's drafts (needs the seed): a tenant role gets a 404 and a malformed id the not-found page; an analyst opens the list from the sidebar in force today (compared with the rulebook's as-of read), the Draft chip listing the drafts of the rules no spec moves, every row a draft, and Every status one row per version the rulebook holds; filters by one rule, opens its draft (the title, the breadcrumb, the not-reviewed warning, the dates, a predicate per attribute of its condition, its open questions, the workflow); an unknown id is the not-found page; axe on each |
| `admin-rulebook-publish.spec.ts` | the publish workflow on three seeded drafts, each first returned to draft through the page when an earlier run left it in review, so the spec runs again on the same stack (needs the seed): citing the recorded notification refused for a quote not in its clause (the failure listed and on its row, the rows kept, nothing stored) and then stored and verified for one that is (read back from the rulebook); submitting as high impact, approving once ("1 of 2 approvals", a second approver needed, the analyst named), and the same analyst's second approval refused under the step with the rulebook's problem; returning a version in review with a reason (too short refused in the dialog); axe on each state; nothing is published or withdrawn |
| `admin-rulebook-entities.spec.ts` | the resolve tool and an entity's page (needs the seed for the resolutions): a tenant role gets a 404, a malformed id the not-found page; an analyst opens the tool from the sidebar and resolves a recorded mention's name, a section without its statute and a code with no digits, each status and normalised name compared with the rulebook's answer; a blank name refused on its field; an entity a name resolves to opened when the rulebook holds one (skipped on a stack without entities); an unknown id is the not-found page |
| `admin-rulebook-search.spec.ts` | the clause search (needs the seed): a tenant role gets a 404; an analyst opens it from the sidebar, searches words of the recorded notification and finds its clause with the ranks the rulebook gives (compared with the service), the words marked, the address unchanged and the words kept, and opens the clause marked in its document; blank words refused with focus on the field; words nothing matches give the empty state; axe on each |
| `admin-rulebook-graph.spec.ts` | the relations graph: a tenant role gets a 404; the form and a malformed id on its field; from a version's page, the graph drawn around it (the start node in the picture, which is hidden from assistive technology) with the relations the rulebook holds from and to it in the table, or the empty state (needs the seed); an unknown id answered on the field with the depth kept; axe |
| `admin-sources.spec.ts`  | the source tools against the pipeline the stack runs: a tenant role gets a 404 for the list, a source and a stored file, a key that cannot be a source's the not-found page; against the stack (needs the seed), an analyst opens the list from the sidebar under the crawl switch (off by default) and finds every source the pipeline lists (the built-in ones exactly; sources other tests stage meanwhile are left out of the count), opens a listing source with its documents and runs and no control, and follows its runs to the pipeline page; an admin's Fetch now of a built-in source, sent only once the pipeline says crawling is off, is refused in plain words and nothing is recorded; an admin renames and pauses a staged source (only what changed is saved, read back from the pipeline) and saving nothing says so; a form opened before another admin paused the source saves only its rename and the pause stands, and its cadence, changed meanwhile by the other admin too, is refused by name with nothing saved; an admin uploads a synthetic PDF to a staged source through the page (the dialog, the plain answer, the document listed and read back), whose bytes stream back with their type, disposition and headers; the upload handler refuses another site, a file that is not a document, a short reason and an analyst, and stores nothing; a stored HTML page is served sandboxed (its script does not run, its image is refused by the policy); an unknown document's file is a plain 404 and a visitor is sent to sign in; axe on each page |
| `admin-pipeline.spec.ts` | the pipeline's operations and a stored document: a tenant role gets a 404 for each page, a malformed id the not-found page; against the stack (needs the seed), an analyst opens the runs from the sidebar (compared with the pipeline's, a backfill filter kept in the address), lists a staged document with how the pipeline reads it and is refused a date range the wrong way round, reads the dead outbox (compared with the pipeline's) with a topic checked on its field, and reads a stored document without the retry (an unknown id is the not-found page); an admin's retry from extract is refused plainly (nothing to extract, then no rule extracted from the type it is read as) and records nothing, and a retry from parse says Temporal did not answer and sends the same request again, the form's own Retry after it included, all under one Idempotency-Key though the page renders again with a new one; axe on each state |
| `admin-pipeline-tasks.spec.ts` | the pipeline's tasks: a tenant role gets a 404; against the stack (needs the seed), an analyst opens them from the sidebar and finds the open tasks, then the triage tasks of every status, as the pipeline lists them (the stack runs no ingest, so none opens: the empty states), read-only; an admin reads the dismissed ones with nothing held back; axe |
| `not-available.spec.ts`  | an admin tool's awaited routes and breadcrumbs, a parameterised tenant route through the catch-all, `/forbidden` for the wrong tenant kind, a planned tool's sentence and note, a ready tool's sentence and what it will use, real 404s with and without a session |
| `forbidden.spec.ts`      | the page and its two links                                                                                                                                |
| `health.spec.ts`         | the health JSON, the static security headers, no `x-powered-by`                                                                                            |
| `owner-onboarding.spec.ts` | the consent step against identity and notification (needs the seed): a new owner of the seeded tenant sees the draft banner with the versions and the unticked boxes, is refused without the required boxes and with a malformed WhatsApp number (values kept, errors focused), agrees with a number of its own, lands on the business step, finds each record with its `<document>@<version>` on the step, and the number opted in on the notification service; a CA admin has no WhatsApp box; a compliance lead is sent to `/forbidden` |
| `owner-onboarding-business.spec.ts` | the business step against identity and profile, each test in a new tenant: without consents only the way back to the consent step; with them, the empty form's field errors (focused), the demo GSTIN typed in lower case with a space pre-filling from the static lookup (the returned values, what was stored, the progress, the link to the questions), the same GSTIN from a fresh form answered as already on file with the same link; a GSTIN the lookup does not know shows the plain note and the review task, and the service holds the named registration with its open `verify_registration` task |
| `owner-onboarding-questions.spec.ts` | the questions step and the summary against profile, in a new tenant with the demo business: the progress from the pre-fill, Not sure stored but not counted and not asked again (the saved note, focus on the new h1), a per-year question naming its year, Save counting, Does not apply counting and listing its review task, a malformed whole number refused under the control (errors focused) then stored, the rest answered Not sure with no question asked twice, the summary's unsure list, the task read back from the service, and "Answer these now" starting again from the first unsure question; an unknown or malformed business id is the streamed not-found page (noindex), and a compliance lead is sent to `/forbidden` |
| `businesses.spec.ts` | the list against profile: the seeded owner with one business goes straight to it; a new owner sees why the list is empty with the way to start; a CA firm with 23 clients made on the service pages through 20 and 3 (status line focused, first page back), searches by name, PAN (any case) and GSTIN with the term in the POST body and the URL unchanged, sees the no-match state and opens a client; a compliance lead reads the list without the add link |
| `owner-settings.spec.ts` | the settings index from the header link: each settings and account page with its status (a live one, a waiting one), the link on to the consents page with its breadcrumbs; a staff member without billing; an analyst sent to `/forbidden` |
| `owner-settings-consents.spec.ts` | the consents page against identity and notification (needs the seed), each test a new user of the seeded tenant with a number of its own: an owner who agreed with a WhatsApp number on the consent step sees each purpose's latest record and the four records, withdraws WhatsApp reminders in the dialog (what is recorded, the remembered number, axe), finds the new record with its evidence and the number opted out on the service, then gives analytics; a staff member gives WhatsApp reminders, is asked for the number, and the number is opted in; a CA admin has no WhatsApp row; a compliance lead has no consent step to go to |
| `owner-settings-notifications.spec.ts` | the notifications page against identity and notification (needs the seed), each test a new user of the seeded tenant with a number or address of its own: an owner whose number the consent step opted in finds it remembered with its recorded preference, saves Hindi and 22:00 to 07:00 (the status line, the service's record, the values after a reload), then opts out; a staff member without the email consent is refused a malformed address on the field, looks up an address typed in capitals (lowercased), cannot switch reminders on (the refusal names the consent), opts out and finds the record on the service, then asks for another address |
| `owner-settings-recipients.spec.ts` | the recipients page against profile and notification, each test in a new tenant with businesses made on the service: an owner opens it from the settings index, adds a recipient of two businesses (a number typed with a space, an address in capitals), finds it listed and read back from the service in that order, changes its language from the Change link, is refused a malformed number (value kept, focus on the summary), and removes it through the dialog (axe on each state); a CA admin is offered the firm's roles; a tenant without a business is asked to add one; a staff member is sent to `/forbidden` |
| `owner-settings-billing.spec.ts` | the billing page against identity, each test in a new tenant: an owner sees each plan the service states (name and description read back from the service, axe), is refused an empty form on its fields, then starts a subscription and sees the state the stack is in: "billing is not connected yet" with the request id, focus on the answer and the values kept (the default, `CW_BILLING_PROVIDER=none`), or the started in-memory subscription without a checkout page (`BILLING=memory`, passed to the spec as `WEB_STACK_BILLING`); a CA admin sees the same plans; a staff member is sent to `/forbidden` |
| `business-pages.spec.ts` | a business made on the service from the demo GSTIN, in a new tenant: the home (the tabs, the registration, the progress, the link to the questions, the screens not built yet), the hierarchy with a location added (field errors, added, already there) and its snapshot all inherited; the attributes for this year (own values from the lookup, an unanswered per-year attribute answered with the version it made, gone in the year before and asked again), the registration inheriting the business's values, the snapshot naming each value's origin in both years, a compliance lead offered no change; the review tasks of a GSTIN no lookup knows; another tenant's business, an unknown id, a malformed id and another tenant's node as the not-found page |
| `owner-reminders.spec.ts` | the reminders pages against notification and profile (needs the seed): the seeded owner opens Reminders from the business's tabs and finds the opt-in confirmation the seed sent, compared with the service's record (template, state, the address masked to its last four digits), filters by its state and by one it is not in, opens it (the record, the error, the id, axe) and goes back; a business without notifications says so; another tenant's business, an unknown and a malformed notification id are the not-found page |
| `journey-owner.spec.ts` | one owner of a new tenant screen after screen against the stack, axe on each: the empty list, the privacy notice read from the consent step and back, the consents with a WhatsApp number and analytics, the demo business with its lookup values, one Not sure, one value and one Does not apply, the summary, the business's five pages by their tabs (the not-applicable task read back from the service), the list now opening the one business, whose home links to adding another and whose profile adds a second GSTIN of the same PAN (no lookup answer, a review task opened), analytics withdrawn on the consents page, the quiet hours of the number opted in at onboarding, a subscribe in the stack's billing state, and signing out |
| `journey-ca-firm.spec.ts` | one CA admin of a new firm against the stack, axe on each screen: the empty client list, the consents without a WhatsApp box, two clients added through onboarding (the demo GSTIN, and one the lookup does not know), both on the list and the second found by a posted search, its `verify_registration` task, the firm's consents and billing |
| `journey-visitor.spec.ts` | a visitor without a session: each legal document from the home page under its draft banner and on paper, `/onboarding` sending them to sign in and back, and the consent step naming the documents at the versions their pages showed (needs the seed for the consent step's read) |
| `owner-obligations.spec.ts` | the obligation list, the calendar and an obligation's page on the memory stack, each test in a new tenant with a business made on the service (the stack has no worker, so no obligation appears): the list from the business's tabs with why it is empty, the filters in the address, a 547-day window refused on its field with nothing listed and a 366-day one asked, clearing the filters; the calendar of February 2000 with its arrow keys, Enter choosing a day, Page Down reading March in place with focus kept and the address following, the month links; the onboarding summary still looking for the first obligation; an unknown, a malformed or another tenant's obligation or business as the not-found page; a compliance lead reading the list, a visitor sent to sign in and an analyst to `/forbidden`; axe on each state |
| `owner-changes.spec.ts` | the changes feed on the memory stack: the feed read from the rulebook first, so the page says nothing is published yet (the stack's rulebook starts with drafts) or shows the newest change as not decided for a business no fan-out has seen; another tenant's, an unknown and a malformed business as the not-found page; a visitor sent to sign in; axe |
| `owner-ask.spec.ts` | ask on the memory stack with `web.qa_enabled` on: the Ask tab, an empty question refused on its field, the registration offered first, a question asked and the page compared with the qa service's answer to the same question (outcome, text, citations), the question kept in its field; not-found for other businesses; axe |
| `admin-decisions.spec.ts` | the decision review against the engine (needs the seed): a tenant role gets a 404; an analyst opens it from the sidebar, is refused a malformed tenant id on its field (kept), looks up the seeded tenant and reads its open items and then every item as the engine lists them (empty on the stack, which has no condition in words to review); a reviewer reads a tenant with no settled item; axe on each |
| `admin-fan-outs.spec.ts` | the fan-out tools against the engine (needs the seed; serial, since the hold is one switch): a tenant role gets a 404, a malformed id the not-found page; an analyst reads the runs (compared with the engine's) and the hold with no control; an admin holds every fan-out (a reason too short keeps the dialog's button off), sees the danger banner with the reason as the engine records it, and releases it, a hold an interrupted run left lifted first; a seeded draft's page with no run, its version, the dry-run link and its rollback refused ("Only a published version can be rolled back"); a reviewer reads it with no control; an id nobody holds is the not-found page; axe on each |
| `admin-impact.spec.ts` | the impact explorer against the engine (needs the seed): a tenant role gets a 404, an analyst and a reviewer the not-found page; an admin opens it from the sidebar, is refused an empty id on its field, dry-runs a seeded draft and a specification at a level (refused first when it is not a JSON object), each compared with the engine's answer to the same request (the stack's directory is empty, so the page says nothing was in scope); the address names the version; axe |
| `ca-change-impact.spec.ts` | a CA firm's affected clients (needs the seed): a visitor is sent to sign in and a business owner to `/forbidden`; a CA admin of a new firm reads a seeded draft's impact, compared with the engine's (no client, zero counts), each filter's empty state, and no bulk card to send since nobody is affected; an unknown and a malformed version are the not-found page; axe |
| `product/journey-product.spec.ts` | project `product`, against `make product` after `make product-seed` (needs `CW_E2E_PRODUCT_URL`; `make product-e2e` sets it): signed in as the seeded synthetic business tenant through "Use the last seeded tenant", the obligation list compared with the service's merged lists and filtered to the ones still to do, the calendar of the first open obligation's month opening it; an obligation's page with its citations and whole clause, both synthetic approvers, the not-yet-reviewed warning and why it applies; a probe business made on the service whose first obligation the onboarding summary's poll finds, started, completed through a dropped answer and "Try again" (the replay said, one closure in the service's history) and commented on; the annual return's change applying to the business in the feed; "When is my GSTR-3B due?" answered from the business's obligations with the service's text and citations; axe on each |
| `product/journey-oversight.spec.ts` | project `product`, after `make product-check` (whose fanout step publishes the annual return): an admin finds the annual return's fan-out completed in the list (compared with the engine), opens it, and sets and releases the global hold with a reason, each compared with the engine (a hold an interrupted run left is lifted first, anyone else's fails the spec); a dry run of the annual return over the synthetic CA firm whose counts and samples are the engine's answer to the same request; the CA firm's admin opens the change's affected clients, sends the change card to a synthetic client contact made for the run (removed afterwards) and sends the same request again: the same outcome per business, said as a replay, and one card per business on the service (queued while the return is published; not affected once CI's rollback step withdrew it). Nothing is withdrawn; axe on each |

Every live page entry in the registry names its spec files in `e2e`, and `screens.test.ts`
checks they exist. A spec is named after what it covers, not after the registry id. The
`journey-*` specs take one person through several screens in the order they would use them;
each screen they reach lists them too, next to its own spec, which covers the screen's states. The
`web-e2e` CI job runs the same command; the fake provider and the fixed secret come from the
Playwright config, so the job needs no extra variable for them.

The seeded-tenant test in `sign-in.spec.ts` reads the file the seed writes
(`seededTenantId()` in `fixtures.ts`: `CW_WEB_SEED_STATE_PATH` relative to `apps/web`, else
`var/seed/last.json` at the repository root, the same default the app uses), picks "Use the
last seeded tenant" on the form, signs in as an owner and finds that tenant id on `/account`.
Without the file it is skipped, except on CI (`CI` set), where the job seeds first and a
missing file fails the test instead. `owner-onboarding.spec.ts` follows the same rule, signs in
as a new user of the seeded tenant (a fresh display name is a fresh user id, so no earlier
run's consents are on file), and reads back what the page wrote with `serviceUrl(service)` in
`fixtures.ts` (`CW_WEB_<SERVICE>_URL`, else `SERVICE_PORT_BASE` plus the service's position,
as `make web-stack` assigns them).

## The product project

The `product` project runs `e2e/product` against the local product rather than the memory stack:
`make product` (the one deployable with its worker on the dev infrastructure; `WEB=0` leaves its
own `next dev` out) and `make product-seed` first, then

```bash
make product-e2e                  # builds the app into .next/e2e-product and runs --project=product
```

which starts `next start` on `PRODUCT_E2E_PORT` (3400) with every `CW_WEB_*_URL` at the internal
listener (`CW_E2E_PRODUCT_URL=http://127.0.0.1:8080`; the config turns it into the app's service
URLs). The spec reads the seed's state file (`var/seed/last.json`, or `CW_WEB_SEED_STATE_PATH`) for
the tenant and its nodes and compares each page with the services' answers, read from the same
listener. It writes as the seeded tenant only to a probe business of its own. The annual
return's change is published by the fanout step of `make product-check`, so the project runs
after the check; on CI the check's rollback step (`--destructive`) has withdrawn that return by
then, and the spec reads its publication, which stays in the feed with the decisions the fan-out
made. `journey-oversight.spec.ts` reads the same run (a completed run stays completed after the
withdrawal), sets and releases the hold, and sends the CA firm's change card to a client contact
of its own; it withdraws nothing, so the shared dev database keeps its published rules and the
rollback is proven by the check's destructive step alone. Without `CW_E2E_PRODUCT_URL` or the
state file it is skipped locally and fails on CI.

## Running things

```bash
pnpm --filter web test                          # unit tests with coverage
pnpm --filter web exec vitest run src/shared    # one directory
pnpm --filter web exec vitest run -t "sitemap"  # tests whose name matches
make web-e2e-install                            # Chromium, once per machine (no install script runs)
make web-stack && make web-stack-wait           # every service on SERVICE_PORT_BASE+1..10, memory stores
make web-seed                                   # the demo tenant and the recorded notification
make web-stack-logs SERVICE=rulebook            # one service's log (every log without SERVICE)
make web-e2e                                    # build, then Playwright on WEB_PORT from .env
make web-stack-down                             # stop the services (memory stores forget their rows)
pnpm --filter web exec playwright test e2e/home.spec.ts        # one spec (needs a built app)
pnpm --filter web exec playwright test -g "skip link"          # tests whose title matches
pnpm --filter web exec playwright test --ui                    # the Playwright UI
pnpm --filter web exec playwright show-report                  # the last HTML report
```

`make web-e2e` sources `.env` for `WEB_PORT`, checks the services it would use (below), builds
the app and runs the suite with `CW_WEB_ENV=test`. Running `playwright test` directly needs a build first (`pnpm --filter web
build`) and, if a dev server is on the port, that server is reused. Reports land in
`apps/web/playwright-report/` and `apps/web/test-results/`, both git-ignored. Typed links are
checked against `.next/types`, which `next build`, `next dev` and `next typegen` write; after
adding a route, run one of them before relying on `tsc` for link errors.

`make web-stack` is the services the app talks to, started as `make run` would start each one
but all at once and on memory stores: pids and logs under `var/web-stack`, the profile's static
GSTIN lookup, the billing provider `none` (`BILLING=memory` starts subscriptions in memory for
a manual demo; give `make web-e2e` the same `BILLING` and the billing spec expects that state),
the KAG layer off, and the rulebook publishing with the write and review tokens from `.env` or
the placeholders `local-write-token` and `local-review-token`, starting with the seed calendar's
draft rule versions (memory store, `CW_RULEBOOK_SEED_ON_START`), so a fresh clone and CI see the
same states (`docs/onboarding/local-dev.md`, "Running a second clone", has the ports). The
Playwright config gives `next start` the same two tokens and turns `web.publish_actions` on.
No page on `main` calls a service yet, so the suite passes without the stack apart from the
seeded-tenant test, which is skipped; with `make web-stack && make web-stack-wait && make
web-seed` first, `make web-e2e` runs everything, as the CI job does. A spec for a page that
reads a service later relies on the same order.

**Never against the shared database.** The chromium specs stage synthetic data through the
services: the review items of the entity and relation specs (`stageReview`), and the sources,
uploads, retries and requeues of the source and pipeline specs. On a memory stack all of it goes
when the stack stops; on a stack started with `STORE=postgres` (the shared development database)
it would stay for good, and a stored document cannot be deleted. So `make web-stack` records its
store and port base in `$(WEB_STACK_DIR)/store` (`store=unknown` when it found services running
that it had not started), `make web-stack-down` removes the record, and the guard in
`apps/web/scripts/stack-guard` refuses the run, with a plain message saying why and what to do,
when a service the run would use answers and is not that recorded memory stack's: a record saying
`postgres` or `unknown`, no record at all (a running stack whose store is unknown counts as
Postgres), another port base, or a port no live process of the stack's pid files was started on.
A service that does not answer passes, since nothing can be staged there. `make web-e2e` runs the
guard before its build, with `CW_E2E_WEB_STACK_DIR` naming its `WEB_STACK_DIR`; the chromium
project's `stack-guard` setup runs it again, so `playwright test` run directly is guarded too
(the directory defaults to `var/web-stack`). `E2E_ALLOW_POSTGRES=1` lets a run go on against such
services, and says so. CI is unaffected: its `make web-stack` is a memory stack in `var/web-stack`
on the default ports. The product project stages none of this: its specs (`e2e/product`) are the
journeys against `make product`, and they depend on no guard. The guard's decision is tested in
the unit suite (`scripts/stack-guard/lib.test.mts`).

`make web-seed` is the seed for that stack (`apps/web/scripts/seed`, run by Node's type
stripping on the openapi-fetch clients typed from the contracts): real HTTP calls only, no mock
and no invented data. Its pure parts run in the unit suite under the node environment:
`seed.test.mts` (the demo facts, the consents' `<document>@<version>` notice versions read from
docs/legal, the service URLs, the arguments, the document id rule, and the recorded rulebook
fixtures: they parse, the recorded PDF hashes to the fixture's digest, every mention is the
exact slice of its clause, every candidate targets a recorded mention and quotes its clause),
`src/test/seed-notices.test.ts` (each seeded consent carries the notice version the web consent
step would record), `http.test.mts` (a recording fetch shows the tenant header on identity,
profile and notification only and the write token on the rulebook admin client only; problem
bodies and connection failures become the printed failure) and `report.test.mts` (the state
file and the summary). The steps themselves are proved by running `make web-stack && make
web-stack-wait && make web-seed` against the real services.

`make check` runs every gate CI runs without Docker, including `web-screens-check`
(`docs/web/screens.md` matches the registry) and `openapi-ts-check` (the TypeScript types under
`packages/contracts/clients/typescript/openapi` match the committed OpenAPI specs; `make
openapi-ts` regenerates them). `pnpm turbo run lint typecheck test build` is the
TypeScript part; `pnpm format` is the prettier check.

## CI

Three jobs in `.github/workflows/ci.yml` cover the app. Two are keyed on the `typescript` path
filter (`apps/**`, `packages/ui/**`, `packages/contracts/**`, the workspace files, and
`docs/legal/**` and `docs/web/**` because the build renders the legal drafts and the tests compare
`docs/web/screens.md` with the registry); `web-e2e` also runs on the `python` filter, and
`dev-stack` on its own `devstack` filter:

- `typescript` runs `pnpm format` and `pnpm turbo run lint typecheck test build` for every
  package. No `CW_WEB_*` variable is set there, so the web build must not need one.
- `dev-stack` (the compose smoke and the local product) also runs the product project: after
  `make product-check` it installs the workspace and Chromium as `web-e2e` does and runs
  `make product-e2e` on the product it started, uploading the Playwright report, the product's
  logs and the seed state on failure. Its path filter includes `apps/web/**`, `packages/ui/**`
  and `pnpm-lock.yaml`, so a web change runs it too (D-047).
- `web-e2e` installs the workspace (pnpm, and uv with Python 3.12 and `uv sync --all-packages
  --locked`, because the services run from the uv workspace), runs `make web-screens-check
  openapi-ts-check` (no other job compares those generated files), starts every service with
  `make web-stack` (8001-8010, memory stores, the stack's fixed demo settings, no container),
  downloads Chromium (`pnpm --filter web e2e:install`; the package has no install script, so
  `strictDepBuilds` stays satisfied) and builds the app with no `CW_WEB_*` variable while the
  services start, waits for their `/health` (`make web-stack-wait`, 120 seconds), seeds them
  (`make web-seed`, which fails the job on any failed step), runs
  `pnpm --filter web e2e --project=chromium` with `PORT=3000` and `CW_WEB_ENV=test`, then always
  prints the tail of every service log and stops the stack. On failure it uploads the Playwright
  report, the test results, the service logs and the seed state.

All three are in the `needs` of the `CI gate` job, the one check branch protection requires;
`make ci-gate-check` fails when a job is missing from that list. Because `web-e2e` starts the
services with the Makefile's recipes and seeds them over HTTP, it also runs when the `python`
filter matches (`services/**`, the shared Python packages, `pyproject.toml`, `uv.lock`, the
`Makefile`, `tools/**`, `evals/**`): a service change that breaks the stack, the seed or a
recorded fixture the seed hashes fails in its own pull request instead of in the next unrelated
web change.
