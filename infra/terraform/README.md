# terraform

Part of the ComplianceWatch monorepo. **Phase 0 structure-only scaffold: no code yet.**
Design reference: Project Foundation guide, sections 12 and 17.

- **Owns:** AWS modules for ap-south-1: network, EKS (node pools: general, workers, gpu, system), Aurora PostgreSQL, MSK, S3, IAM (IRSA)
- **Owning team:** Platform and Infrastructure (guide section 14)
- **Consumes:** n/a
- **Emits / publishes:** Staging and production environments

## Layout

Flat for now; module layout is Platform's Phase 0 deliverable.

## How to run

Not implemented yet. Driven from the repo root (`make dev`, `make test`; guide section 13) once the service template lands.
