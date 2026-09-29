# web app

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 10, 12, 14 and 15.

- **Owns:** Next.js 16 app: owner portal, CA dashboard, and the /admin internal tools (review workbench, source manager, pipeline console, eval dashboard, prompt and model registry, ontology editor, tenant admin, impact explorer, notification console, cost dashboard, backfill and replay, feature flag console)
- **Owning team:** Core Product (review workbench UI: Regulatory Intelligence; tenant admin: Identity and Partner) (guide section 14)
- **Consumes:** the services' REST APIs through a server-only layer (the browser never calls a service); packages/ui
- **Emits / publishes:** n/a (UI)

## Layout

```
src/app/            route files only: page.tsx is gate, query, render; layouts, error, global-error, not-found
  (public)/         home, /sitemap, /legal/[doc], /forbidden under the visitor shell
  (app)/            tenant screens under AppShell; [...slug] serves waiting and planned tenant screens
  admin/            /admin home and layout under AdminShell; [...slug] serves waiting and planned tools
  api/health/       liveness handler {status, version, commit}
src/features/       one directory per screen family: ports.ts, gateway.ts, queries.ts, actions.ts, model/, ui/, index.ts
                    today: home, sitemap, legal, not-available, admin-home, system-pages
src/entities/       pure domain types and DTO-to-view mappers (no React, no fetch, no next imports)
src/server/         server-only modules; every file starts with `import "server-only"`
                    legal.ts reads docs/legal at build time (marked); runtime.ts reads CW_WEB_ENV (default local)
src/shared/config/  the screen registry (screens.ts), roles and permissions, flags, navigation
src/shared/lib/     IST dates, financial years, money and decimal strings, identifiers, pagination, urls
src/shared/i18n/    messages/en.json and the typed t(); another locale falls back key by key
src/shared/ui/      app-level compositions over the UI kit: the two shells over next/link, breadcrumbs, the status chip
src/test/           vitest setup and the architecture rules
src/app/globals.css Tailwind v4 plus the UI kit's token file (@compliancewatch/ui/styles/tokens.css)
src/instrumentation.ts  onRequestError writes one JSON line (digest, route, x-request-id) to stderr
next.config.ts      typed routes, security headers; eslint.config.mjs: Next flat config plus repo rules
vitest.config.mts   jsdom, Testing Library, 80% coverage floor (route files are covered by e2e)
playwright.config.ts  Playwright against `next start` on PORT with CW_WEB_ENV=test; chromium only
e2e/                fixtures.ts (the axe check failing on serious or critical) and one spec per live page,
                    plus a11y.spec.ts over every registered page; tsconfig.scripts.json type-checks them
```

Import rules (checked by `src/test/architecture.test.ts` over the real tree): `app` imports
`features`, `shared`, `entities` and `server`; `features` import `shared`, `entities`, `server`
and their own files; `entities` import `shared/lib` only; `server` imports `server`, `shared`
and `entities`; `shared` imports `shared`. A client component (`"use client"`) imports `shared`,
`entities` and its own directory only. The contracts package is imported type-only. Files under
`shared/config` and `shared/lib` use explicit `.ts` relative imports and no `@/` alias so plain
Node scripts can load them.

Every screen is an entry in `src/shared/config/screens.ts` before anything else exists: the
navigation, breadcrumbs, sitemap, the "not available yet" pages and the route-coverage test
read the registry. `screens.test.ts` checks each entry against the committed OpenAPI specs
(`packages/contracts/openapi`): a live entry only calls routes that exist and has its page file;
a waiting entry names at least one route or file that is still absent and has no page file (the
catch-all routes serve it); a planned entry awaits routes nobody has scheduled. When an awaited
route lands, the test fails with "backend merged: flip `<id>` to live". Roles and role sets in
`roles.ts` are copied from the identity design; `permissions.ts` maps capabilities to roles.

User-visible chrome strings go through `t("key")` from `src/shared/i18n` (keys are typed from
`messages/en.json`; a test checks every literal exists). Screen titles are registry data. Dates
render in Asia/Kolkata through `shared/lib/dates.ts`, financial years as `2026-27`, and money
from paise or decimal strings without float arithmetic.

Colours come from the token classes (`bg-bg`, `text-fg`, `border-line`, ...); the eslint config
rejects hex literals in class strings.

A screen whose backend routes do not exist has no page file: the two catch-all routes match
the pathname against the registry and render `NotAvailableYet` with the awaited routes, their
owner and the guide reference (an unknown path is a 404). Legal pages render the drafts in
`docs/legal` under the draft banner, prerendered from the three listed names. `/admin` lists
every internal tool from the registry with its status and the services it depends on. There is
no `loading.tsx` above the catch-alls on purpose: a loading boundary above `notFound()` streams
the page with status 200, so a later package adds `loading.tsx` beside each page that fetches.
`CW_WEB_ENV` is read directly by `server/runtime.ts` (unset means local; an unknown value is
treated as prod) until the validated environment module lands.

## End-to-end tests

The Playwright suite visits the built app without any service: the public pages, the admin
home, the design catalogue (group by group) and every waiting or planned page through the
catch-alls, with `AxeBuilder` failing a page on any serious or critical finding. Once per
machine: `pnpm --filter web e2e:install` (downloads Chromium; the package has no install script).
Then `pnpm --filter web build && PORT=3200 pnpm --filter web e2e` (any free port; the config
starts `next start` there with `CW_WEB_ENV=test`, or reuses a server already on it outside CI).
Every live page entry in the registry names its spec files under `e2e`, and the registry test
checks they exist. Playwright reports land in `playwright-report/` and `test-results/`, both
git-ignored.

## How to run

`pnpm --filter web dev` (http://localhost:3000 and /admin), `build`, `test`, `lint`, `typecheck`.
`next dev` maintains `AGENTS.md` (Next.js agent rules); keep it committed. Typed links are
validated against `.next/types`, which `next build`, `next dev` and `next typegen` write; run one
of them after adding a route before relying on `tsc` for link checks.
