# ui package

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 12, 13 and 15.

- **Owns:** Shared React components and design tokens (Tailwind, shadcn/ui) used by the product and the internal tools
- **Owning team:** Core Product (guide section 14)
- **Consumes:** n/a
- **Emits / publishes:** Consumed by apps/web

## Layout

```
src/index.ts     # public exports
src/badge.tsx    # first component: <Badge tone="neutral|success|warning|danger">
```
Consumed from source via `exports` and Next's `transpilePackages`; no build step.

## How to run

`pnpm --filter @compliancewatch/ui test` (vitest + Testing Library, 80% coverage thresholds), `lint`, `typecheck`.
