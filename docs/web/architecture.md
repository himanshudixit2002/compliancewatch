# Architecture

`apps/web` is a Next.js 16 app (App Router, React 19, Tailwind v4) that renders every screen on
the server and ships small client components for the pieces that need the browser: the two
shells (they read the current pathname to mark the active link), the design catalogue and its
theme control, and the error boundaries. The browser never calls a service. There is no
`NEXT_PUBLIC_*` variable and no token reaches a client bundle. The server-side data layer
(`server/`: the validated environment, the typed clients, the encrypted session cookie, the
gates and the sign-in provider port) is where every service call and every session decision
lives; no page on `main` calls a service yet, and the reads today are `docs/legal/*.md` at
build time, `CW_WEB_ENV` per request and the session cookie. The rule is a platform decision,
[ADR-019](../adr/ADR-019-web-server-layer-and-stateless-session.md);
[data-layer.md](data-layer.md) has the clients, headers, errors, caching and the seed, and
[auth-and-roles.md](auth-and-roles.md) the session, the gates and the sign-in.

## Layers

Everything under `apps/web/src` belongs to one of five layers. `src/test/architecture.test.ts`
reads the real tree, extracts every import specifier and fails on a forbidden edge, so the
table is enforced, not advisory.

| Layer                       | Holds                                                                                                                           | May import                                                            |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `app/`                      | Route files only: `page.tsx`, `layout.tsx`, `route.ts`, `error.tsx`, `not-found.tsx`. A page is thin: gate, query, render.      | `features`, `shared`, `entities`, `server`                            |
| `features/<name>/`          | One directory per screen family: `model/` (pure view-model helpers with tests), `ui/` (components), `index.ts` (the public API). | `shared`, `entities`, `server`, its own directory                     |
| `entities/<name>/`          | Pure domain types and DTO-to-view mappers: `types.ts`, `mappers.ts`, `mappers.test.ts`. No React, no `next`, no fetch.          | `shared/lib`, its own directory                                       |
| `server/`                   | Server-only modules; every file starts with `import "server-only"`.                                                             | `server`, `shared`, `entities`                                        |
| `shared/`                   | Isomorphic code: `config/` (registry, roles, permissions, flags, navigation), `lib/`, `i18n/`, `ui/` (app-level compositions).  | `shared` only; never `server-only`, `next/headers`, `next/server`, `node:` |
| root (`proxy.ts`, `instrumentation.ts`) | Framework hooks: the optimistic check before a render, the error hook.                                              | `server`, `shared`, `entities`                                        |

Three more rules apply across layers. A feature never imports another feature (shared pieces go
to `shared/ui` or `entities`). A client component (`"use client"`) imports `shared`, `entities`
and its own directory subtree only, so a server module can never reach a client bundle through a
feature. `@compliancewatch/contracts` is imported type-only from app code.

Files under `shared/config` and `shared/lib` use explicit `.ts` relative imports and no `@/`
alias. That is what lets plain Node 22 load the registry without a bundler: the docs generator
(`scripts/screens-doc.mts`) and the Playwright specs import it directly.

A feature that reads data will add `ports.ts` (the interface it needs), `gateway.ts` (the
implementation over a typed client, server-only), `queries.ts` (server-only page reads returning
a `Result`) and `actions.ts` (server actions) next to `model/` and `ui/`. `features/auth` is the
first with `actions.ts` (the sign-in action) and `queries.ts` (the seed state); no feature calls
a service yet. A client component receives a server action as a prop from its page (the sign-in
form takes `action` and the options the page built), because the layer rule keeps client
components to `shared`, `entities` and their own directory.

## Directory map

```
apps/web/
  src/app/
    layout.tsx                 <html lang="en">, globals.css, the Toaster
    (public)/                  home, /sitemap, /legal/[doc], /forbidden, /design, /sign-in; the visitor shell
    (app)/                     tenant screens under the session-aware shell: /account and the catch-all [...slug]
    admin/                     /admin (the tool list), the admin layout behind requireAdmin, the catch-all [...slug]
    sign-out/route.ts          POST: clears the session cookie
    api/health/route.ts        {status, version, commit}
    error.tsx, global-error.tsx, not-found.tsx
  src/features/                home, sitemap, legal, not-available, admin-home, system-pages, design-catalogue,
                               auth (sign-in form, action, seed state), account
  src/entities/                screen/ (the view shapes of a registry entry), problem/ (RFC 9457), session/ (the claims),
                               ontology/ (the attributes and their wording from GET /v1/ontology)
  src/server/                  env.ts (validated CW_WEB_*, parsed lazily), result.ts (Result, ApiError, webError),
                               api/ (typed clients, problem parsing, idempotency), cache.ts (tags and revalidation),
                               session.ts (the cookie), dal.ts (the gates), origin.ts (the same-origin check of a
                               POST handler), auth/ (the provider port and the fake adapter), legal.ts,
                               ontology.ts (the ontology read, cached an hour by tag)
  src/shared/config/           screens.ts, roles.ts, permissions.ts, flags.ts, nav.ts, services.ts, legal-docs.ts
  src/shared/lib/              dates, financial years, decimal money, humanise, identifiers, pagination, urls, assert
  src/shared/i18n/             messages/en.json and t()
  src/shared/ui/               TenantShell, InternalShell, RouterLink, Breadcrumbs, ScreenStatusChip, SessionMenu,
                               SignOutButton
  src/test/                    vitest setup, the architecture rules and their test, the screens.md drift test,
                               fake-fetch.ts and fake-cookies.ts
  src/proxy.ts                 the optimistic redirect to /sign-in for gated screens without a cookie
  src/instrumentation.ts       onRequestError: one JSON line per server error
  scripts/screens-doc.mts      generates docs/web/screens.md; --check and --audit modes
  scripts/seed/                the demo-tenant seed over the services' HTTP APIs (make web-seed)
  e2e/                         Playwright specs and the axe fixture
```

## The screen registry

`shared/config/screens.ts` exports `SCREENS`, one entry per screen whether it is built or not.
Everything that needs to know what screens exist reads this list: the header and sidebar
navigation (`nav.ts`), the home page links, `/sitemap`, the `/admin` tool list, the two catch-all
routes, the accessibility sweep in `e2e/a11y.spec.ts`, and the generated `screens.md`. A screen
exists here before anything else exists.

An entry carries:

- `id`: a dot path starting with the section (`owner.obligations`, `admin.review`,
  `system.home`).
- `kind`: `page` (owns a route), `handler` (a route handler), `component` or `capability`
  (embedded in the page named by `route`). Only pages take part in route matching.
- `route`: Next segment syntax, for example `/b/[businessId]/obligations/[obligationId]`.
- `title`, `section` (`owner`, `ca`, `account`, `admin`, `system`), `roles` (a list of role ids
  or `"public"`), optional `tenantKinds` and `flag`.
- `uses`: the service routes the screen calls today; each must exist in a committed OpenAPI spec.
- `awaits`: the service routes it still needs, each with an `owner` (`plan-a` for the services
  track, `plan-k` for the KAG track, `unplanned` for nobody) and a `ref` (the delivering package
  or a note). KAG-track paths carry `unconfirmed: true` until that track's specs are committed.
  `awaitsFiles` names a repository file instead of a route (the flag registry).
- `status`: `planned`, `waiting`, `ready` or `live`, in the order a screen moves through them
  (below).
- `preview`: the name of a component the not-available page may render under the notice; none
  is registered today.
- `e2e`: the Playwright spec files that visit a live page.
- `guideRef`, `nav` (group and order), `parent` (for breadcrumbs), `notes`.

A screen's status moves planned, then waiting, then ready, then live:

| Status    | Backend                                                            | Page file | Served by |
| --------- | ------------------------------------------------------------------ | --------- | --------- |
| `planned` | nobody has scheduled it; every awaited item is `unplanned`         | none      | catch-all |
| `waiting` | at least one awaited route or file is absent from `main`           | none      | catch-all |
| `ready`   | every awaited route and file is on `main`; the screen is not built | none      | catch-all |
| `live`    | every `uses` route is in a committed spec; the screen is built     | its own   | its own   |

`screens.test.ts` holds the status rules. A live page has its `page.tsx` (a handler its
`route.ts`) and names at least one existing e2e spec, and every `uses` path is in a committed
spec. A ready entry names at least one route or file, every route and file it awaits is present,
every awaited route is also under `uses`, and it has no page file. A waiting entry awaits at
least one route or file that is absent, lists any awaited route that is already present under
`uses` as well, and has no page file. A planned entry awaits only from `unplanned` and has no
page file. Every `page.tsx` and `route.ts` under `src/app` is registered exactly once (route
groups such as `(public)` are stripped). When every awaited item of a waiting entry has landed,
the test fails with `backend merged: flip <id> to ready (or live once built)`. The change that
sees it moves the entry to `ready`; building the screen is the work of the package that owns it,
which then sets `live` ([adding-a-screen.md](adding-a-screen.md), D-013 in
[decisions.md](decisions.md)). A few screens whose routes all existed before they were listed
(the obligation list and calendar, ask, and some rulebook tools) are not registered yet; each
can join as a ready entry with its routes under `uses`.

Helpers: `screenById`, `matchScreen(pathname)` (the most specific page entry with its decoded
parameters), `hrefFor(screen, params)` (a typed href; a missing parameter throws), `screensFor`
and `isVisibleTo` (role and tenant-kind filtering), `routeParams`, `toRoutePattern`. `nav.ts`
derives `publicNav`, `navFor` (the tenant groups), `adminNavFor` (the admin groups) and
`breadcrumbsFor` (the parent chain); a flagged entry is hidden unless the caller's
`isFlagEnabled` says otherwise, and an entry whose route parameters are unknown on the current
request is left out.

## Not available yet

A planned, waiting or ready screen has no page file. `(app)/[...slug]/page.tsx` and
`admin/[...slug]/page.tsx` match the pathname against the registry and render the entry through
`NotAvailablePage`: the title as the page's `h1`, the guide reference, the roles, and each awaited
route as `METHOD /path` with its owner label (`services track (WP22)`, `KAG track`,
`not scheduled`), or one sentence saying no backend exists yet. For a ready entry the notice
says instead that the backend for the screen is on main and the screen has not been built, and
lists the awaited routes and files followed by the other routes the entry uses (labelled with
their service). A `notes` text and, when the entry names one, a preview component follow. Breadcrumbs come from the parent chain and the back
link goes to the section's home. A path that matches nothing is a real 404 (`notFound()`); a live
entry never reaches a catch-all because its own page file wins. There is no `loading.tsx` above
the catch-alls on purpose: a loading boundary above `notFound()` streams the page with status 200.

## Roles and capabilities

`shared/config/roles.ts` hard-codes the eight roles (`owner`, `staff`, `ca_admin`, `ca_staff`,
`compliance_lead`, `analyst`, `reviewer`, `admin`), the three tenant kinds (`business`,
`ca_firm`, `internal`), the role sets (tenant members, tenant admins, regulatory roles, roles
that need MFA), the roles each tenant kind allows and the first role of a new tenant. The values
are copied from the identity service's design; the comment in the file names the source and the
test that will compare them once `domain_kernel/access.py` exists. `permissions.ts` maps
capabilities (`obligations.read`, `admin.publish`, `team.manage`, ...) to role lists and offers
`can(principal, capability)`. The registry's `roles` and these sets decide what the navigation
shows and what `screens.md`'s matrix says.

The gates live in `server/dal.ts` and read the session cookie (`server/session.ts`, a JWE the
server encrypts; `entities/session` holds the claims and the render-safe view). A page calls
its gate on the first line: `requireScreenSession(SCREEN)` for a tenant screen, `requireAdmin()`
under `/admin` (a tenant role gets a 404, so it does not learn that a tool exists), and the two
catch-alls apply the matched entry's roles and tenant kinds with `requireScreen`. An anonymous
visitor is sent to `/sign-in?next=` (`src/proxy.ts` does this before the render when no cookie
is present at all; the gate does it authoritatively), a wrong role to `/forbidden`. The sign-in
page asks the provider port (`server/auth/provider.ts`) for the claims; the only adapter today
is the fake one, which exists where `CW_WEB_ENV` is `local` or `test`, and `/sign-out` (POST)
clears the cookie. `/design` keeps its environment gate: 404 unless the value is `local` or
`test` (unset means local; an unknown value is refused at the first request, so a typo never
opens it). The shells read `sessionForRender()` for their links and the account menu and never
decide whether to render. [auth-and-roles.md](auth-and-roles.md) has the claims, the cookie,
every gate and what the identity work changes.

## Request flow

```mermaid
flowchart TD
  B[Browser] -->|GET /admin/review| N[Next.js server]
  N --> H[next.config.ts static headers]
  H --> X["src/proxy.ts: gated screen or /admin without cw_session -> /sign-in?next="]
  X --> R["app/layout.tsx: html, globals.css, Toaster"]
  R --> G{route group}
  G -->|"(public)"| TS["(public)/layout.tsx: TenantShell with publicNav()"]
  G -->|"(app)"| TA["(app)/layout.tsx: TenantShell with the session's links and menu"]
  G -->|admin| AS["admin/layout.tsx: requireAdmin(), InternalShell with the session's tools"]
  TS --> P[page.tsx: metadata from the registry, gate, render a feature view]
  TA --> C1["(app)/[...slug]: matchScreen(), requireScreen() then NotAvailablePage or notFound()"]
  AS --> P2[admin/page.tsx: requireAdmin(), adminToolGroups from the registry]
  AS --> C2["admin/[...slug]: matchScreen(), requireScreen() then NotAvailablePage or notFound()"]
  P --> F[features/*/ui view over packages/ui components]
  C1 --> F
  P2 --> F
  C2 --> F
  F --> B
  P -. throws .-> E[error.tsx in the shell; instrumentation.ts writes one JSON line]
```

A page that reads a service adds one step after its gate: `features/<name>/queries.ts` calls a
gateway, the gateway calls a typed client from `server/api`, and the answer comes back as a
`Result` the page renders or shows as `ErrorState` (the sequence is in
[data-layer.md](data-layer.md)).

The legal pages read `docs/legal/<doc>.md` at build time (`server/legal.ts`, `marked` with its
defaults; a test asserts the drafts contain no raw HTML tag), prerender the three listed
documents and render each under the fixed "Draft - to be reviewed by a lawyer" banner with its
`Version:` line. `/design` and the admin layout are `force-dynamic` so the environment answer is
never baked into the build.

Errors: `error.tsx` renders `ErrorState` inside the segment's shell with the error digest as the
reference to quote, `global-error.tsx` does the same with its own `<html>`, and
`instrumentation.ts`'s `onRequestError` writes one JSON line to stderr with the digest, path,
method, route and the `x-request-id` header it received, so a log search finds the line the
page refers to.

## Environments, ports and configuration

- `CW_WEB_*`: every variable the app reads, validated by `server/env.ts` (zod). `getEnv()`
  parses the process environment at its first call from a request, action or route handler,
  never at import, and keeps the frozen result; a bad value is refused with the variable's
  name. `CW_WEB_ENV` is `local`, `test`, `staging` or `prod` (unset means local; the Playwright
  config starts `next start` with `test`); the service URLs default to the canonical ports
  8001-8010; `CW_WEB_AUTH_PROVIDER` names the sign-in adapter (`fake` in local and test only);
  the session secret is required only where a session is encrypted or decrypted.
  `apps/web/.env.example` lists every variable with its default. Every module works with no
  `CW_WEB_*` variable set; `pnpm turbo run build` with an empty environment is part of the
  checklist.
- `PORT`: what `next dev` and `next start` listen on. `make web-dev` and `make web-e2e` pass
  `WEB_PORT` from the root `.env` (3000 unless changed; a second working copy uses 3200, see
  `docs/onboarding/local-dev.md`). `apps/web/.env.example` lists the variables the app reads.
- `SERVICE_PORT_BASE` (root `.env`, 8000 unless changed): `make web-stack` starts every service
  on the base plus 1 to 10 in the Makefile's `SERVICES` order with memory stores and fixed demo
  settings, `make web-stack-wait` waits for their health, `make web-stack-down` stops them. The
  app's `CW_WEB_*_URL` values name the same ports (their defaults are the 8000 base).
- `next.config.ts`: `reactStrictMode`, `poweredByHeader: false`, `transpilePackages` for the UI
  kit (consumed from source), `typedRoutes` (registry hrefs go through `hrefFor()` so typed links
  accept them), and the four static security headers (`vercel.json` carries the same set).
- `tsconfig.json`: `@/*` for `src`, ES2022 (bigint literals in the money helpers),
  `allowImportingTsExtensions`; `scripts/` and `e2e/` are checked by `tsconfig.scripts.json`
  (NodeNext, `erasableSyntaxOnly`) because plain Node runs them. `pnpm --filter web typecheck`
  runs both.
- `eslint.config.mjs`: the Next flat config plus `consistent-type-imports` and a rule that
  rejects a hex colour inside a `className` string or a `cn()` call, so colours go through the
  token classes.
- `vitest.config.mts`: jsdom, Testing Library, the 80% coverage floor with route files excluded
  ([testing.md](testing.md)).
- `turbo.json`: the `build` task hashes `CW_WEB_*` and `docs/legal/*.md`; the `test` task hashes
  `docs/legal/*.md`, `docs/web/screens.md` and the committed OpenAPI specs, because tests read
  them.

## Ports and adapters

Two ports are in use. The shells' `Link` prop: `packages/ui`'s `AppShell` and `AdminShell`
take a link component so the kit stays free of `next/link`, and `shared/ui/router-link.tsx`
supplies `next/link` from the app. And the sign-in provider: `server/auth/provider.ts` declares
`AuthProvider` (`startSignIn`, `completeSignIn`, `signOut`, the methods it offers) and
`providerFor(env)` picks the adapter named by `CW_WEB_AUTH_PROVIDER`; `server/auth/fake.ts` is
the only adapter today, and the identity work adds the real one without touching the pages.
The feature files reserved above (`ports.ts`, `gateway.ts`) follow the same idea for data: a
feature declares what it needs, a server-only adapter implements it over the typed clients, and
tests inject a fake fetch ([data-layer.md](data-layer.md), "A feature that reads data").
`features/not-available/ui/previews.tsx` is a registry of preview components keyed by the name
a registry entry may carry; it is empty until a package ships the first preview.
