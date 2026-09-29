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
| `shared/i18n`                    | every `t("...")` literal in `src` exists in `en.json`; interpolation; the key-by-key fallback                                               |
| `shared/lib`                     | IST rendering, financial-year labels, decimal money, identifiers, `safeNext`                                                               |
| `server/legal.ts`                | version and title extraction, and that no file in `docs/legal` contains a raw HTML tag (marked does not sanitise)                          |
| `server/session.ts`, `dal.ts`    | the cookie round trip (tamper, expiry, wrong key, wrong shape), the cookie attributes per environment, each gate's redirect or 404 (the cookie store from `src/test/fake-cookies.ts`) |
| `server/auth/*`                  | `providerFor` per variable value; the fake adapter's validation, stable user id, second-factor assertion and refusal outside local and test |
| `features/auth`                  | the form (roles per kind, the busy state, the errors it shows) with a fake action; the action's cookie and redirect; the seed-state reader |
| `src/proxy.ts`                   | the matcher through `next/experimental/testing/server` and the pass-or-redirect decision for every registry page (excluded from the coverage floor) |
| `src/test/architecture.test.ts`  | the layer rules over the real tree                                                                                                         |
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
`COMPLIANCE_LEAD`, `CA_ADMIN`, `ANALYST`, `ADMIN`) are signed in once per worker through the
fake form and their cookies are added to the test's context, so a spec that needs a session
starts with `await signIn(ANALYST)`; `signInThroughForm(page, persona, next?)` drives the form
itself for the specs that test it.

The specs on `main`:

| Spec                     | Covers                                                                                                                                                    |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `a11y.spec.ts`           | every page in the registry except the catch-alls and the legal route, grouped by the first persona its roles and tenant kinds admit (public pages without a session): live pages by their route, planned, waiting and ready pages through the catch-all with `example` for each parameter; one h1, status 200, the notice on non-live pages, axe |
| `home.spec.ts`           | the landing links, the skip link moving focus to `main`, the sign-in link leading to the form                                                              |
| `sign-in.spec.ts`        | the redirect with `next` from a gated page, the server's field errors, a refused submit keeping every value and focusing the errors, an owner signing in, returning to `/account`, the account menu and signing out, the role homes (`/businesses`, `/admin`), a signed-in visit to `/sign-in`, the last seeded tenant offered by the form and signed into (needs the seed), the roles following the tenant kind, `/sign-out` as POST only with the origin check, signing in and out through `127.0.0.1` (a host other than the one `next start` binds) |
| `account.spec.ts`        | the session facts in IST, the copy controls, the note on `/me`, the header name linking to `/account`                                                     |
| `admin-gate.spec.ts`     | anonymous `/admin` to sign-in with `next`, a 404 for a tenant role on every admin path, an analyst opening the tools without the admin-only entries and a 404 on one of them |
| `sitemap.spec.ts`        | one table per section, a waiting tool's awaited route and owner, a ready tool's chip, the link to its notice                                              |
| `legal.spec.ts`          | each listed document under the draft banner with its `-draft` version; an unlisted document is a 404                                                        |
| `design.spec.ts`         | every catalogue section with axe, the theme control, dialogs (focus, Escape, the ten-character reason), the calendar keys                                   |
| `admin-home.spec.ts`     | as an analyst: the tool list with status (waiting and ready) and service READMEs, the environment banner, sidebar navigation marking the current tool     |
| `not-available.spec.ts`  | an admin tool's awaited routes and breadcrumbs, a parameterised tenant route through the catch-all, `/forbidden` for the wrong tenant kind, a planned tool's sentence and note, a ready tool's sentence and what it will use, real 404s with and without a session |
| `forbidden.spec.ts`      | the page and its two links                                                                                                                                |
| `health.spec.ts`         | the health JSON, the static security headers, no `x-powered-by`                                                                                            |
| `owner-onboarding.spec.ts` | the consent step against identity and notification (needs the seed): a new owner of the seeded tenant sees the draft banner with the versions and the unticked boxes, is refused without the required boxes and with a malformed WhatsApp number (values kept, errors focused), agrees, lands on the business step, finds each record with its `<document>@<version>` on the step, and the number opted in on the notification service; a CA admin has no WhatsApp box; a compliance lead is sent to `/forbidden` |

Every live page entry in the registry names its spec files in `e2e`, and `screens.test.ts`
checks they exist. A spec is named after what it covers, not after the registry id. The
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
GSTIN lookup, the billing provider `none`, the publish flow and the KAG layer off, and the
rulebook write token from `.env` or the placeholder `local-write-token`, so a fresh clone and CI
see the same states (`docs/onboarding/local-dev.md`, "Running a second clone", has the ports).
No page on `main` calls a service yet, so the suite passes without the stack apart from the
seeded-tenant test, which is skipped; with `make web-stack && make web-stack-wait && make
web-seed` first, `make web-e2e` runs everything, as the CI job does. A spec for a page that
reads a service later relies on the same order.

`make web-seed` is the seed for that stack (`apps/web/scripts/seed`, run by Node's type
stripping on the openapi-fetch clients typed from the contracts): real HTTP calls only, no mock
and no invented data. Its pure parts run in the unit suite under the node environment:
`seed.test.mts` (the demo facts, the service URLs, the arguments, the document id rule, and the
recorded rulebook fixtures: they parse, the recorded PDF hashes to the fixture's digest, every
mention is the exact slice of its clause, every candidate targets a recorded mention and quotes
its clause), `http.test.mts` (a recording fetch shows the tenant header on identity, profile and
notification only and the write token on the rulebook admin client only; problem bodies and
connection failures become the printed failure) and `report.test.mts` (the state file and the
summary). The steps themselves are proved by running `make web-stack && make web-stack-wait &&
make web-seed` against the real services.

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
