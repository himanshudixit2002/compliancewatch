# web app

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 10, 12, 14 and 15.

- **Owns:** Next.js 16 app: owner portal, CA dashboard, and the /admin internal tools (review workbench, source manager, pipeline console, eval dashboard, prompt and model registry, ontology editor, tenant admin, impact explorer, notification console, cost dashboard, backfill and replay, feature flag console)
- **Owning team:** Core Product (review workbench UI: Regulatory Intelligence; tenant admin: Identity and Partner) (guide section 14)
- **Consumes:** the services' REST APIs through a server-only layer (the browser never calls a service); packages/ui
- **Emits / publishes:** n/a (UI)

## Layout

```
src/app/            route files only: page.tsx is gate, query, render; layout, loading, error, not-found
src/features/       one directory per screen family: ports.ts, gateway.ts, queries.ts, actions.ts, model/, ui/, index.ts
src/entities/       pure domain types and DTO-to-view mappers (no React, no fetch, no next imports)
src/server/         server-only modules; every file starts with `import "server-only"`
src/shared/         isomorphic code: config (registry, roles, nav), lib helpers, i18n, app-level ui
src/test/           vitest setup and the architecture rules
src/app/globals.css Tailwind v4 plus the UI kit's token file (@compliancewatch/ui/styles/tokens.css)
next.config.ts      typed routes, security headers; eslint.config.mjs: Next flat config plus repo rules
vitest.config.mts   jsdom, Testing Library, 80% coverage floor (route files are covered by e2e)
```

Import rules (checked by `src/test/architecture.test.ts` over the real tree): `app` imports
`features`, `shared`, `entities` and `server`; `features` import `shared`, `entities`, `server`
and their own files; `entities` import `shared/lib` only; `server` imports `server`, `shared`
and `entities`; `shared` imports `shared`. A client component (`"use client"`) imports `shared`,
`entities` and its own directory only. The contracts package is imported type-only. Files under
`shared/config` and `shared/lib` use explicit `.ts` relative imports and no `@/` alias so plain
Node scripts can load them.

Colours come from the token classes (`bg-bg`, `text-fg`, `border-line`, ...); the eslint config
rejects hex literals in class strings.

## How to run

`pnpm --filter web dev` (http://localhost:3000 and /admin), `build`, `test`, `lint`, `typecheck`.
`next dev` maintains `AGENTS.md` (Next.js agent rules); keep it committed. Typed links are
validated against `.next/types`, which `next build`, `next dev` and `next typegen` write; run one
of them after adding a route before relying on `tsc` for link checks.
