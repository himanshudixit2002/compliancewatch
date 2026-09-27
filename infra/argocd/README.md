# argocd

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
Design reference: Project Foundation guide, sections 13 and 17.

- **Owns:** Argo CD application definitions; Argo Rollouts canary (5%, 25%, 100%) with automatic rollback on SLO breach
- **Owning team:** Platform and Infrastructure (guide section 14)
- **Consumes:** n/a
- **Emits / publishes:** GitOps deploys to staging (every merge) and production (promoted by the owning team)

## Layout

Flat for now.

## How to run

Not implemented yet. Driven from the repo root (`make dev`, `make test`; guide section 13) once the service template lands.
