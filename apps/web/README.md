# web app

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
Design reference: Project Foundation guide, sections 10, 12, 14 and 15.

- **Owns:** Next.js 15 app: owner portal, CA dashboard, and the /admin internal tools (review workbench, source manager, pipeline console, eval dashboard, prompt and model registry, ontology editor, tenant admin, impact explorer, notification console, cost dashboard, backfill and replay, feature flag console)
- **Owning team:** Core Product (review workbench UI: Regulatory Intelligence; tenant admin: Identity and Partner) (guide section 14)
- **Consumes:** Public REST API v1 through the API gateway; packages/ui
- **Emits / publishes:** n/a (UI)

## Layout

No internal structure yet: to be generated with `create-next-app` in Phase 0 (React, TypeScript, Tailwind, shadcn/ui).

## How to run

Not implemented yet. Driven from the repo root (`make dev`, `make test`; guide section 13) once the service template lands.
