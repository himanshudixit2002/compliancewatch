# Testing

Two levels. Unit tests (vitest, jsdom, Testing Library) cover everything that can render or run
without a request scope: components, view models, mappers, config, helpers, server modules
called directly. The Playwright suite covers what unit tests cannot: the route files (a
`page.tsx` is an async server component that needs a request), the shells with real
navigation, the built app's headers and status codes, and page-level accessibility. Both levels
run axe. No test uses a mock service, and no e2e test uses a mock of anything: the suite on
`main` visits only pages that need no service.

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
| `src/test/architecture.test.ts`  | the layer rules over the real tree                                                                                                         |
| `src/test/screens-doc.test.ts`   | `docs/web/screens.md` equals the generator's output; the awaits audit                                                                      |
| `packages/ui` tokens             | `contrast.test.ts` (4.5:1 text, 3:1 UI, both schemes), `tokens.test.ts` (the two dark blocks agree), `tokens.build.test.ts` (the utilities compile) |
| `packages/ui/src/imports.test.ts`| internal imports are relative, never `@/` or the package name                                                                              |

## End-to-end tests

`apps/web/playwright.config.ts` runs the specs in `apps/web/e2e` against `next start` on `PORT`
(3000 unless set) with `CW_WEB_ENV=test`, chromium only, and waits for `/api/health` before the
first test. Outside CI it reuses a server already listening on that port. On CI it retries once
and writes the HTML report. `e2e/fixtures.ts` extends `test` with `checkA11y(selector?)`, which
runs `AxeBuilder` on the page (or one selector) and fails on any finding of impact `serious` or
`critical`; moderate and minor findings are the unit level's business.

The specs on `main`:

| Spec                     | Covers                                                                                                                                                    |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `a11y.spec.ts`           | every page in the registry except the catch-alls and the legal route: live pages by their route, waiting and planned pages through the catch-all with `example` for each parameter; one h1, status 200, the notice on non-live pages, axe |
| `home.spec.ts`           | the landing links, the skip link moving focus to `main`, the sign-in link leading to the waiting notice                                                    |
| `sitemap.spec.ts`        | one table per section, a waiting tool's awaited route and owner, the link to its notice                                                                    |
| `legal.spec.ts`          | each listed document under the draft banner with its `-draft` version; an unlisted document is a 404                                                        |
| `design.spec.ts`         | every catalogue section with axe, the theme control, dialogs (focus, Escape, the ten-character reason), the calendar keys                                   |
| `admin-home.spec.ts`     | the tool list with status and service READMEs, the environment banner, sidebar navigation marking the current tool                                          |
| `not-available.spec.ts`  | an admin tool's awaited routes and breadcrumbs, a parameterised tenant route through the catch-all, a planned tool's sentence and note, real 404s           |
| `forbidden.spec.ts`      | the page and its two links                                                                                                                                |
| `health.spec.ts`         | the health JSON, the static security headers, no `x-powered-by`                                                                                            |

Every live page entry in the registry names its spec files in `e2e`, and `screens.test.ts`
checks they exist. A spec is named after what it covers, not after the registry id.

## Running things

```bash
pnpm --filter web test                          # unit tests with coverage
pnpm --filter web exec vitest run src/shared    # one directory
pnpm --filter web exec vitest run -t "sitemap"  # tests whose name matches
make web-e2e-install                            # Chromium, once per machine (no install script runs)
make web-e2e                                    # build, then Playwright on WEB_PORT from .env
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

`make check` runs every gate CI runs without Docker, including `web-screens-check`
(`docs/web/screens.md` matches the registry). `pnpm turbo run lint typecheck test build` is the
TypeScript part; `pnpm format` is the prettier check.

## CI

Two jobs in `.github/workflows/ci.yml` cover the app, both keyed on the `typescript` path filter
(`apps/**`, `packages/ui/**`, `packages/contracts/**`, the workspace files):

- `typescript` runs `pnpm format` and `pnpm turbo run lint typecheck test build` for every
  package. No `CW_WEB_*` variable is set there, so the web build must not need one.
- `web-e2e` installs the workspace, runs `make web-screens-check`, downloads Chromium
  (`pnpm --filter web e2e:install`; the package has no install script, so `strictDepBuilds`
  stays satisfied), builds the app with no `CW_WEB_*` variable, runs `pnpm --filter web e2e`
  with `PORT=3000` and `CW_WEB_ENV=test`, and uploads the Playwright report and test results
  when the run fails.

Both are in the `needs` of the `CI gate` job, the one check branch protection requires;
`make ci-gate-check` fails when a job is missing from that list.
