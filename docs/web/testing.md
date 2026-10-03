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
catalogue's `fixtures.test.ts`, which name the tokens in order to reject them. A new test uses the
example forms above; a live page whose test seems to need a realistic token gets synthetic data
instead, or one narrow entry in the allow list with the reason.

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
| `server/api/rulebook-write.ts`   | the role, the flag and the review token checked in that order (a refused port answers every decision without a request), each token sent only by its own client and never in an error, `decided_by` from the session, the decision bodies and answers mapped, the rulebook's token problems reworded to name the variable to set |
| `server/session.ts`, `dal.ts`    | the cookie round trip (tamper, expiry, wrong key, wrong shape), the cookie attributes per environment, each gate's redirect or 404 (the cookie store from `src/test/fake-cookies.ts`) |
| `server/auth/*`                  | `providerFor` per variable value; the fake adapter's validation, stable user id, second-factor assertion and refusal outside local and test |
| `features/auth`                  | the form (roles per kind, the busy state, the errors it shows) with a fake action; the action's cookie and redirect; the seed-state reader |
| `src/proxy.ts`                   | the matcher through `next/experimental/testing/server` and the pass-or-redirect decision for every registry page (excluded from the coverage floor) |
| `src/test/architecture.test.ts`  | the layer rules over the real tree; the parked folder map: every feature folder no route file imports is parked for registry screens that exist and are not live, and a folder a page imports leaves the map ([architecture.md](architecture.md), "Parked feature folders") |
| `src/test/synthetic-fixtures.test.ts` | no realistic token in a test or a fixture of the web app or the UI kit ("Synthetic fixtures" above) |
| `src/test/screens-doc.test.ts`   | `docs/web/screens.md` equals the generator's output; the awaits audit                                                                      |
| `packages/ui` tokens             | `contrast.test.ts` (4.5:1 text, 3:1 UI, both schemes), `tokens.test.ts` (the two dark blocks agree), `tokens.build.test.ts` (the utilities compile) |
| `packages/ui/src/imports.test.ts`| internal imports are relative, never `@/` or the package name                                                                              |

## End-to-end tests

`apps/web/playwright.config.ts` runs the specs in `apps/web/e2e` against `next start` on `PORT`
(3000 unless set) with `CW_WEB_ENV=test`, `CW_WEB_AUTH_PROVIDER=fake` and a fixed session
secret (32 bytes of `e2e`; it keys the cookies of one run and is not a secret), chromium only,
and waits for `/api/health` before the first test. Outside CI it reuses a server already
listening on that port. On CI it retries once and writes the HTML report. `e2e/fixtures.ts`
extends `test` with `checkA11y(selector?)`, which runs `AxeBuilder` on the page (or one
selector) and fails on any finding of impact `serious` or `critical` (moderate and minor
findings are the unit level's business), and with `signIn(persona)`: the personas (`OWNER`,
`COMPLIANCE_LEAD`, `CA_ADMIN`, `ANALYST`, `REVIEWER`, `ADMIN`) are signed in once per worker through the
fake form and their cookies are added to the test's context, so a spec that needs a session
starts with `await signIn(ANALYST)`; `signInThroughForm(page, persona, next?)` drives the form
itself for the specs that test it.

The specs on `main`:

| Spec                     | Covers                                                                                                                                                    |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `a11y.spec.ts`           | every page in the registry except the catch-alls and the live pages with route parameters (a legal document, a business: `example` is a 404 there, so their own specs visit them with real ones and run axe), grouped by the first persona its roles and tenant kinds admit (public pages without a session): live pages by their route, planned, waiting and ready pages through the catch-all with `example` for each parameter; one h1, status 200, the notice on non-live pages, axe |
| `home.spec.ts`           | the landing links, the skip link moving focus to `main`, the sign-in link leading to the form                                                              |
| `sign-in.spec.ts`        | the redirect with `next` from a gated page, the server's field errors, a refused submit keeping every value and focusing the errors, an owner signing in, returning to `/account`, the account menu and signing out, the role homes (`/businesses`, `/admin`), a signed-in visit to `/sign-in`, the last seeded tenant offered by the form and signed into (needs the seed), the roles following the tenant kind, `/sign-out` as POST only with the origin check, signing in and out through `127.0.0.1` (a host other than the one `next start` binds) |
| `account.spec.ts`        | the session facts in IST, the copy controls, the note on `/me`, the header name linking to `/account`                                                     |
| `admin-gate.spec.ts`     | anonymous `/admin` to sign-in with `next`; a 404 without any admin markup for an owner and a compliance lead on every admin path; an analyst opening the tools without the admin-only entries and a 404 on one of them; a reviewer and an admin opening the tools; an unknown admin path as a 404 inside the admin shell with the way back (axe) |
| `sitemap.spec.ts`        | one table per section, a waiting tool's awaited route and owner, a ready tool's chip, the link to its notice                                              |
| `legal.spec.ts`          | each listed document under the draft banner with its `-draft` version; an unlisted document is a 404; printed (print media, light and dark schemes): no shell, the banner kept, the paper line, black text on white |
| `design.spec.ts`         | every catalogue section with axe, the theme control, dialogs (focus, Escape, the ten-character reason), the calendar keys                                   |
| `admin-home.spec.ts`     | as an analyst: the tool list with status (waiting and ready) and service READMEs, the environment banner, sidebar navigation marking the current tool, the "Waiting" hint of a tool not built yet as its link's description; against the stack (needs the seed): a number and no error in each count tile, the open mentions, every service answering its health check (axe); the counts are not compared with numbers, since other specs change the queues |
| `admin-rulebook-documents.spec.ts` | a tenant role getting a 404 for the tool and the viewer; a malformed id as a real 404 inside the admin shell; against the recorded notification the seed registers (needs the seed): opened from its sha256 through the form (the current sidebar link, axe), the title, the reference in the breadcrumbs, every clause with its anchor and page, the id; an unknown id answered on the field (focused, value kept) and a 404 on the viewer; a jump to a clause (the address fragment, focus on the clause); a mention's span marked from a link with the clause ids read from the rulebook (the note, focus, axe), the whole clause when the span runs past it, a clause the document does not hold, a malformed link. Read-only, so it runs in parallel and again on the same stack |
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
| `owner-settings-billing.spec.ts` | the billing page against identity, each test in a new tenant: an owner sees each plan the service states (name and description read back from the service, axe), is refused an empty form on its fields, then starts a subscription and sees the state the stack is in: "billing is not connected yet" with the request id, focus on the answer and the values kept (the default, `CW_BILLING_PROVIDER=none`), or the started in-memory subscription without a checkout page (`BILLING=memory`, passed to the spec as `WEB_STACK_BILLING`); a CA admin sees the same plans; a staff member is sent to `/forbidden` |
| `business-pages.spec.ts` | a business made on the service from the demo GSTIN, in a new tenant: the home (the tabs, the registration, the progress, the link to the questions, the screens not built yet), the hierarchy with a location added (field errors, added, already there) and its snapshot all inherited; the attributes for this year (own values from the lookup, an unanswered per-year attribute answered with the version it made, gone in the year before and asked again), the registration inheriting the business's values, the snapshot naming each value's origin in both years, a compliance lead offered no change; the review tasks of a GSTIN no lookup knows; another tenant's business, an unknown id, a malformed id and another tenant's node as the not-found page |
| `journey-owner.spec.ts` | one owner of a new tenant screen after screen against the stack, axe on each: the empty list, the privacy notice read from the consent step and back, the consents with a WhatsApp number and analytics, the demo business with its lookup values, one Not sure, one value and one Does not apply, the summary, the business's five pages by their tabs (the not-applicable task read back from the service), the list now opening the one business, whose home links to adding another and whose profile adds a second GSTIN of the same PAN (no lookup answer, a review task opened), analytics withdrawn on the consents page, the quiet hours of the number opted in at onboarding, a subscribe in the stack's billing state, and signing out |
| `journey-ca-firm.spec.ts` | one CA admin of a new firm against the stack, axe on each screen: the empty client list, the consents without a WhatsApp box, two clients added through onboarding (the demo GSTIN, and one the lookup does not know), both on the list and the second found by a posted search, its `verify_registration` task, the firm's consents and billing |
| `journey-visitor.spec.ts` | a visitor without a session: each legal document from the home page under its draft banner and on paper, `/onboarding` sending them to sign in and back, and the consent step naming the documents at the versions their pages showed (needs the seed for the consent step's read) |

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

`make web-e2e` sources `.env` for `WEB_PORT`, builds the app and runs the suite with
`CW_WEB_ENV=test`. Running `playwright test` directly needs a build first (`pnpm --filter web
build`) and, if a dev server is on the port, that server is reused. Reports land in
`apps/web/playwright-report/` and `apps/web/test-results/`, both git-ignored. Typed links are
checked against `.next/types`, which `next build`, `next dev` and `next typegen` write; after
adding a route, run one of them before relying on `tsc` for link errors.

`make web-stack` is the services the app talks to, started as `make run` would start each one
but all at once and on memory stores: pids and logs under `var/web-stack`, the profile's static
GSTIN lookup, the billing provider `none` (`BILLING=memory` starts subscriptions in memory for
a manual demo; give `make web-e2e` the same `BILLING` and the billing spec expects that state),
the publish flow and the KAG layer off, and the rulebook write token from `.env` or the
placeholder `local-write-token`, so a fresh clone and CI see the same states (`docs/onboarding/local-dev.md`, "Running a second clone", has the ports).
No page on `main` calls a service yet, so the suite passes without the stack apart from the
seeded-tenant test, which is skipped; with `make web-stack && make web-stack-wait && make
web-seed` first, `make web-e2e` runs everything, as the CI job does. A spec for a page that
reads a service later relies on the same order.

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

Two jobs in `.github/workflows/ci.yml` cover the app, both keyed on the `typescript` path filter
(`apps/**`, `packages/ui/**`, `packages/contracts/**`, the workspace files, and `docs/legal/**`
and `docs/web/**` because the build renders the legal drafts and the tests compare
`docs/web/screens.md` with the registry); `web-e2e` also runs on the `python` filter:

- `typescript` runs `pnpm format` and `pnpm turbo run lint typecheck test build` for every
  package. No `CW_WEB_*` variable is set there, so the web build must not need one.
- `web-e2e` installs the workspace (pnpm, and uv with Python 3.12 and `uv sync --all-packages
  --locked`, because the services run from the uv workspace), runs `make web-screens-check
  openapi-ts-check` (no other job compares those generated files), starts every service with
  `make web-stack` (8001-8010, memory stores, the stack's fixed demo settings, no container),
  downloads Chromium (`pnpm --filter web e2e:install`; the package has no install script, so
  `strictDepBuilds` stays satisfied) and builds the app with no `CW_WEB_*` variable while the
  services start, waits for their `/health` (`make web-stack-wait`, 120 seconds), seeds them
  (`make web-seed`, which fails the job on any failed step), runs `pnpm --filter web e2e` with
  `PORT=3000` and `CW_WEB_ENV=test`, then always prints the tail of every service log and stops
  the stack. On failure it uploads the Playwright report, the test results, the service logs
  and the seed state.

Both are in the `needs` of the `CI gate` job, the one check branch protection requires;
`make ci-gate-check` fails when a job is missing from that list. Because `web-e2e` starts the
services with the Makefile's recipes and seeds them over HTTP, it also runs when the `python`
filter matches (`services/**`, the shared Python packages, `pyproject.toml`, `uv.lock`, the
`Makefile`, `tools/**`, `evals/**`): a service change that breaks the stack, the seed or a
recorded fixture the seed hashes fails in its own pull request instead of in the next unrelated
web change.
