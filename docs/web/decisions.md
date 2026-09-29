# Decisions

Choices local to the web app, numbered `D-001` onward, newest last. Each entry records the
date, the context, the decision and its consequences. A choice that binds other parts of the
platform (how services are called, how a session is carried) is an ADR under `docs/adr/` and is
referenced from here rather than restated; the first of those is written together with the
server-side data layer, which is not on `main` yet.

## D-001: The browser never calls a service

2026-09-29. Services have no CORS, the rulebook's writes need a shared token, and the tenant is
identified by a header today. Every service call goes through the Next.js server, and the app
has no `NEXT_PUBLIC_*` variable: no service URL and no token is compiled into a client bundle.
Consequences: pages read on the server and render; client components get plain props; the
server-side data layer is the only place a base URL or a token lives; `apps/web/.env.example`
holds server-read variables only. The cross-cutting form of this decision (the session cookie
and the header contract with the services) becomes an ADR when the data layer lands.

## D-002: shadcn primitives are generated once into `packages/ui` and owned

2026-09-29. A component library as a dependency would pin the app to its release cadence and its
colour system. The primitives were generated with the shadcn CLI (`shadcn@4.21.0`, the command
is in `design-system.md`), post-processed to relative imports and token classes, and are edited
in place; the CLI is not a dependency and never runs on CI. Consequences: `radix-ui` and five
small runtime dependencies, no build step, every component has its own test and its
accessibility contract in the file; upgrading shadcn means regenerating a file and re-applying
the post-processing, which the README records.

## D-003: The screen registry is data and drives navigation, docs and tests

2026-09-29. With about a hundred screens, most of them waiting for a backend, a hand-kept
navigation, a hand-kept sitemap and a hand-kept docs table would drift. `shared/config/screens.ts`
is one list; navigation, breadcrumbs, the home links, the sitemap, the admin tool list, the
not-available pages, the accessibility sweep and `screens.md` read it, and `screens.test.ts`
checks it against the route tree and the committed OpenAPI specs. Consequences: a screen exists
in the registry before its files; a landed backend fails a test ("backend merged: flip") rather
than going unnoticed; the generated doc is the canonical screen list; the config files use
explicit `.ts` imports so plain Node can load them.

## D-004: No `cacheComponents`

2026-09-29. Next 16's `cacheComponents` mode is opt-in and changes what a page may read during
render. Every tenant screen reads a cookie and is dynamic by nature, and the few global reads
(plans, templates, rules) fit fetch-level revalidation with tags. The option stays off;
authenticated pages export `dynamic = "force-dynamic"` explicitly when they arrive.
Consequences: the caching model is fetch options and `revalidatePath`/`updateTag` in actions;
`/design` and the admin layout are already `force-dynamic` because they read `CW_WEB_ENV`.

## D-005: No `authInterrupts`

2026-09-29. `forbidden()` and `unauthorized()` are experimental in 16.3.6. A failed gate calls
`notFound()` under `/admin` (a non-regulatory role must not learn that a tool exists) or
redirects to `/forbidden` elsewhere. Consequences: `/forbidden` is a public page with a way out
(home, sign in with another account); the not-found page brings its own shell because it renders
below the root layout.

## D-006: English only, with a translator that can take Hindi

2026-09-29. No i18n framework: `en.json` is a flat typed table, `t()` interpolates `{name}`,
and `createTranslator("hi")` falls back key by key to English until `hi.json` exists. Screen
titles and navigation labels are registry data, not keys, because the config files must load
under plain Node. Consequences: a test scans `src` for `t()` literals; enum values are
humanised, not translated per value; date and money wording goes through the helpers in
`shared/lib`; the Hindi file, when written, is checked against the English key set.

## D-007: A catalogue page instead of Storybook

2026-09-29. A component workbench would add a second build, its own dependencies and a second
place to keep in step with the tokens. `/design` renders every component in every state inside
the real app, with a control that forces light or dark, and exists only where `CW_WEB_ENV` is
`local` or `test`. Consequences: the Playwright suite checks the catalogue section by section
with axe; the example data is synthetic by construction and a test rejects the regulatory
vocabulary in it; a new component is added to the catalogue in the same change.

## D-008: Two catch-all routes render every waiting and planned screen

2026-09-29. A three-line `page.tsx` per waiting screen would be about forty near-empty files
that drift from the registry. `(app)/[...slug]` and `admin/[...slug]` match the pathname against
the registry and render `NotAvailableYet` with the awaited routes, their owner and the guide
reference; a waiting or planned entry must not have a page file (the test fails if one
appears), and an unknown path is a real 404. Consequences: there is no `loading.tsx` above the
catch-alls (a loading boundary above `notFound()` streams a 200), so a later page that fetches
adds `loading.tsx` beside itself; the notice never shows sample data.

## D-009: System font stacks, no font download at build

2026-09-29. `next/font` fetches font files at build time, which needs network on every build
and adds a failure mode for nothing the product needs. The token file declares
`ui-sans-serif, system-ui, ...` and `ui-monospace, ...`; the contrast and type-scale tests do
not depend on a font. Consequences: builds are offline-safe; Devanagari text, when it comes,
renders in the system's font.

## D-010: The axe matcher is fifteen lines over `axe-core`

2026-09-29. `vitest-axe` has one release from 2022 with unverified typings against vitest 4;
`axe-core` was already in the lockfile through `eslint-config-next`. `packages/ui/src/test/axe.ts`
runs axe with the `region` and `color-contrast` rules off (a lone component has no landmarks;
jsdom cannot measure colour) and adds `toHaveNoViolations` to `expect`; `apps/web` imports it
through the package's `./test/axe` export. Consequences: one matcher for both packages;
page-level colour and landmark checks belong to the Playwright suite and the contrast test.

## D-011: The e2e suite runs against `next start` and needs no service

2026-09-29. On `main` no page calls a service, so the suite builds the app, starts it with
`CW_WEB_ENV=test` and visits every registered page: live pages by their route, waiting and
planned ones through the catch-alls. Consequences: `make web-e2e` and the `web-e2e` CI job need
no container; the health handler is the readiness signal; a suite that needs services will
start them explicitly and seed through their HTTP APIs, never through a mock.

## D-012: `CW_WEB_ENV` is read directly until a validated environment module exists

2026-09-29. Two callers need the environment name (the internal shell's label and the design
catalogue's gate) and nothing else is read from the environment yet. `server/runtime.ts` reads
the one variable: unset means `local`, and an unknown value counts as `prod` so a typo never
opens a local-only page. Consequences: the build needs no `CW_WEB_*` variable (checked with an
empty environment); the validated, memoised environment module that arrives with the data layer
replaces this file's reader without changing its callers.
