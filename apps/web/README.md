# web app

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 10, 12, 14 and 15.

- **Owns:** Next.js 16 app: owner portal, CA dashboard, and the /admin internal tools (review workbench, source manager, pipeline console, eval dashboard, prompt and model registry, ontology editor, tenant admin, impact explorer, notification console, cost dashboard, backfill and replay, feature flag console). On `main`: the foundation (screen registry, roles, navigation, i18n, helpers), the public pages, the `/admin` tool list, the not-available pages for every screen whose backend is absent, the legal pages and the design catalogue
- **Owning team:** Core Product; the `/admin` routes belong to Regulatory Intelligence (CODEOWNERS) (guide section 14)
- **Consumes:** the services' REST APIs through a server-only layer (the browser never calls a service; no page calls one yet); `docs/legal` at build time; packages/ui
- **Emits / publishes:** n/a (UI)

The reasoning behind the layout, the design system, the tests and the screen procedure is in
[docs/web](../../docs/web/README.md); this file is the map and the commands.

## Layout

```
src/app/            route files only: page.tsx is gate, query, render; layouts, error, global-error, not-found
  (public)/         home, /sitemap, /legal/[doc], /forbidden, /design under the visitor shell
  (app)/            tenant screens under AppShell; [...slug] serves unbuilt tenant screens
  admin/            /admin home and layout under AdminShell; [...slug] serves unbuilt tools
  api/health/       liveness handler {status, version, commit}
src/features/       one directory per screen family: model/, ui/, index.ts (ports, gateway, queries and
                    actions join when a feature reads data); today: home, sitemap, legal, not-available,
                    admin-home, system-pages, design-catalogue
src/entities/       pure domain types and DTO-to-view mappers (no React, no fetch, no next imports);
                    problem/ types the RFC 9457 body every service returns (from the generated contracts)
src/server/         server-only modules; every file starts with `import "server-only"`
                    env.ts validates every CW_WEB_* variable (zod; parsed at the first request, never at build)
                    result.ts: Result, ApiError and the mapping to a form's ActionState
                    api/client.ts: one openapi-fetch client per service (x-request-id, accept, time limit) and call()
                    api/problem.ts: RFC 9457 parsing to ApiError kinds and field errors
                    api/services.ts: the client factories (tenant header from the session; rulebookAdmin() adds
                    the write token after a regulatory-role check)
                    legal.ts reads docs/legal at build time (marked)
src/shared/config/  the screen registry (screens.ts), roles and permissions, flags, navigation, the legal doc list
src/shared/lib/     IST dates, financial years, money and decimal strings, humanise, identifiers, pagination, urls,
                    action-state (what a server action returns to a form)
src/shared/i18n/    messages/en.json and the typed t(); another locale falls back key by key
src/shared/ui/      app-level compositions over the UI kit: the two shells over next/link, breadcrumbs, the status chip
src/test/           vitest setup, the architecture rules and test, the docs/web/screens.md drift test,
                    fake-fetch.ts (a recording fetch with problem+json answers for client and gateway tests)
src/app/globals.css Tailwind v4 plus the UI kit's token file (@compliancewatch/ui/styles/tokens.css)
src/instrumentation.ts  onRequestError writes one JSON line (digest, route, x-request-id) to stderr
scripts/screens-doc.mts generates docs/web/screens.md from the registry (screens:gen, screens:check, screens:audit)
e2e/                fixtures.ts (the axe check failing on serious or critical) and one spec per live page,
                    plus a11y.spec.ts over every registered page; tsconfig.scripts.json type-checks them
next.config.ts      typed routes, security headers; eslint.config.mjs: Next flat config plus repo rules
vitest.config.mts   jsdom, Testing Library, 80% coverage floor (route files are covered by e2e)
playwright.config.ts  Playwright against `next start` on PORT with CW_WEB_ENV=test; chromium only
.env.example        every CW_WEB_* variable the app reads, with its default; copy to .env.local
```

Import rules (checked by `src/test/architecture.test.ts` over the real tree): `app` imports
`features`, `shared`, `entities` and `server`; `features` import `shared`, `entities`, `server`
and their own files; `entities` import `shared/lib` only; `server` imports `server`, `shared`
and `entities`; `shared` imports `shared`. A client component (`"use client"`) imports `shared`,
`entities` and its own directory only. The contracts package is imported type-only. Files under
`shared/config` and `shared/lib` use explicit `.ts` relative imports and no `@/` alias so plain
Node scripts can load them.

Every screen is an entry in `src/shared/config/screens.ts` before anything else exists: the
navigation, breadcrumbs, sitemap, the "not available yet" pages, the route-coverage test and the
generated `docs/web/screens.md` read the registry. `screens.test.ts` checks each entry against
the committed OpenAPI specs (`packages/contracts/openapi`): a live entry only calls routes that
exist and has its page file; a ready entry's awaited routes and files are all on `main` but it
has no page file yet; a waiting entry names at least one route or file that is still absent and
has no page file (the catch-all routes serve ready and waiting entries); a planned entry awaits
routes nobody has scheduled. When the last awaited item lands, the test fails with "backend
merged: flip `<id>` to ready (or live once built)". Roles and role sets in `roles.ts` are copied
from the identity design; `permissions.ts` maps capabilities to roles. The procedure is in
[docs/web/adding-a-screen.md](../../docs/web/adding-a-screen.md).

User-visible chrome strings go through `t("key")` from `src/shared/i18n` (keys are typed from
`messages/en.json`; a test checks every literal exists). Screen titles are registry data. Dates
render in Asia/Kolkata through `shared/lib/dates.ts`, financial years as `2026-27`, and money
from paise or decimal strings without float arithmetic.

Colours come from the token classes (`bg-bg`, `text-fg`, `border-line`, ...); the eslint config
rejects hex literals in class strings.

A screen that is not built has no page file: the two catch-all routes match the pathname against the
registry and render `NotAvailableYet` with the awaited routes, their owner and the guide reference,
or for a ready screen the sentence that its backend is on main (an unknown path is a 404). Legal
pages render the drafts in `docs/legal` under the draft banner, prerendered from the three listed
names. `/admin` lists every internal tool from the registry with its status and the services it
depends on. There is no `loading.tsx` above the catch-alls on purpose: a loading boundary above
`notFound()` streams the page with status 200, so a later package adds `loading.tsx` beside each
page that fetches. `server/env.ts` validates every `CW_WEB_*` variable with zod: `getEnv()` parses
the process environment at the first request (never at import or build time), keeps the frozen
result, and refuses a bad value with the variable's name; unset means the documented default
(`CW_WEB_ENV` local, the services on their canonical ports 8001-8010). The service clients
(`server/api`) are typed from the generated contracts and used only on the server; no page calls one
yet, and no session or gate exists: every page renders for every visitor.

## End-to-end tests

The Playwright suite visits the built app without any service: the public pages, the admin
home, the design catalogue (group by group) and every planned, waiting or ready page through
the catch-alls, with `AxeBuilder` failing a page on any serious or critical finding. Once per
machine: `make web-e2e-install` (downloads Chromium; the package has no install script). Then
`make web-e2e` builds the app and runs the suite on `WEB_PORT` from the root `.env` (3000 unless
changed; the config starts `next start` there with `CW_WEB_ENV=test`, or reuses a server already
on it outside CI). Every live page entry in the registry names its spec files under `e2e`, and
the registry test checks they exist. Playwright reports land in `playwright-report/` and
`test-results/`, both git-ignored. On CI the `web-e2e` job runs the same suite.

## How to run

`make web-dev` (or `pnpm --filter web dev`; http://localhost:3000, `/admin` for the tool list,
`/design` for the UI kit, `/sitemap` for every screen and its status), `pnpm --filter web
build`, `test`, `lint`, `typecheck` (both tsconfigs), `e2e`. Copy `.env.example` to
`.env.local` for anything that must differ from the defaults; the build needs no variable at all.
`pnpm --filter web screens:gen` regenerates `docs/web/screens.md` (`screens:check` compares,
`make web-screens-check` in `make check`; `screens:audit` lists the awaited routes still absent
from the committed specs). `next dev` maintains `AGENTS.md` (Next.js agent rules); keep it
committed. Typed links are validated against `.next/types`, which `next build`, `next dev` and
`next typegen` write; run one of them after adding a route before relying on `tsc` for link
checks.
