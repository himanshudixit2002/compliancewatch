# web app

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 10, 12, 14 and 15.

- **Owns:** Next.js 16 app: owner portal, CA dashboard, and the /admin internal tools (review workbench, source manager, pipeline console, eval dashboard, prompt and model registry, ontology editor, tenant admin, impact explorer, notification console, cost dashboard, backfill and replay, feature flag console)
- **Owning team:** Core Product (review workbench UI: Regulatory Intelligence; tenant admin: Identity and Partner) (guide section 14)
- **Consumes:** Public REST API v1 through the API gateway; packages/ui
- **Emits / publishes:** n/a (UI)

## Layout

```
src/app/layout.tsx, page.tsx      # App Router; Tailwind v4 via @tailwindcss/postcss
src/app/admin/page.tsx            # /admin placeholder for the internal tools
src/app/*.test.tsx                # vitest + Testing Library (jsdom)
next.config.ts, eslint.config.mjs # Next.js 16: Turbopack by default, ESLint flat config
```

## How to run

`pnpm --filter web dev` (http://localhost:3000 and /admin), `build`, `test`, `lint`, `typecheck`. `next dev` maintains `AGENTS.md` (Next.js agent rules); keep it committed.
