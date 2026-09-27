# ComplianceWatch monorepo

> **Phase 0 structure-only scaffold.** This repository currently contains directories, placeholder files and ownership metadata only: no application code, no dependency manifests, no CI. It is the starting point for Phase 0 ("Monorepo with the service template") of the ComplianceWatch roadmap.
>
> Source of truth: *ComplianceWatch - Project Foundation (HLD, LLD & Build Guide)*. Section numbers below refer to that guide.

ComplianceWatch watches regulators for rule changes, decides which changes apply to one specific business, and turns each into a dated obligation the owner can act on. Launch vertical: Indian SMBs under GST, with FSSAI as the second regulator (section 1).

## Layout principles (section 13)

One monorepo, one directory per service, one shared contracts package that every service builds against, and a `CODEOWNERS` file that maps each directory to exactly one team. A change to a contract needs a review from every consuming team; a change inside a service needs only its owner.

## Repository tree

```
compliancewatch/
  apps/
    web/                     # Next.js: owner portal, CA dashboard, /admin internal tools
    whatsapp-bot/            # Webhook receiver and conversation state (TypeScript)
  services/                  # One FastAPI or worker service per directory (Python)
    identity/
    profile/
    rulebook/
    applicability-engine/
    obligation/
    notification/
    qa/
    llm-gateway/
    eval/
    pipeline/                # crawler, detector, parser, extractor, review as Temporal workers
      adapters/              # SourceAdapter implementations, one file per regulator source
      parsers/
      prompts/               # Versioned prompt files, each with a test
      workflows/
  packages/
    contracts/               # OpenAPI specs, event schemas (JSON Schema), generated clients (py + ts)
      openapi/  events/  clients/python/  clients/typescript/
    domain-kernel/           # Shared value objects, protocols, Ontology loader, error types
    ontology/                # Attribute definitions as YAML, versioned, with a validator
    py-common/               # Logging, tracing, config, auth middleware, outbox, testing fakes
    ui/                      # Shared React components and design tokens
  infra/
    terraform/               # AWS modules: network, EKS, Aurora, MSK, S3, IAM
    helm/                    # One chart per service, values per environment
    argocd/                  # Application definitions
  evals/
    golden/                  # Golden sets: extraction/, qa/, applicability/ (versioned data files)
    harness/                 # Runner, metrics, thresholds
  docs/
    adr/                     # Architecture decision records, numbered (ADR-001..011 stubs)
    runbooks/
    onboarding/
  .github/workflows/         # CI pipelines, affected-only (empty until Phase 0 CI lands)
  CODEOWNERS
  Makefile                   # make dev, make test, make eval, make migrate (stubs)
```

## Inside every Python service (identical shape)

```
services/<name>/
  src/<package>/
    api/            # routers, schemas, dependencies
    application/    # use cases, event handlers, unit of work
    domain/         # entities, value objects, events, repositories (protocols)
    infrastructure/ # sqlalchemy models, repositories, kafka, adapters
    main.py         # composition root (added by the service template)
  migrations/       # alembic
  tests/
    unit/           # domain and application with fakes; no I/O
    integration/    # testcontainers: postgres, kafka
    contract/       # provider-side contract tests for this service's API and events
  pyproject.toml    # added by the service template
  Dockerfile        # added by the service template
  README.md         # what it owns, how to run, who owns it
```

Python package names are the directory name with hyphens replaced by underscores, with two exceptions chosen so the package never shadows the standard library or a builtin:

| Service directory | Package |
| --- | --- |
| `profile` | `profile_service` (the stdlib ships a `profile` module) |
| `eval` | `eval_service` (`eval` is a builtin) |
| `applicability-engine` | `applicability_engine` |
| `llm-gateway` | `llm_gateway` |
| all others | same as the directory name |

`services/pipeline/{adapters,parsers,prompts,workflows}` sit directly under the service, as drawn in section 13; the CI eval trigger (section 17) watches `services/pipeline/prompts`. The code directories may move under `src/pipeline/` when the service template lands.

## Ownership (section 14)

`CODEOWNERS` maps every directory to its owning team. GitHub teams do not exist yet, so every line names the repository owner and records the intended team in a comment. Teams: Regulatory Intelligence, AI Platform, Core Product, Platform and Infrastructure, Identity and Partner, and the Regulatory Analysts (domain). Phase 0 starts with two combined teams: Platform and Pipeline, Product and AI.

## Make targets (section 13)

`make dev`, `make test`, `make eval`, `make migrate`. All four are stubs that print "not implemented yet".

## Conventions to be enforced by tooling (section 13; not wired yet)

| Convention | Enforced by |
| --- | --- |
| No import from another service's package | import-linter contract in CI |
| Domain layer imports nothing from infrastructure or third-party I/O | import-linter |
| Every public endpoint has an OpenAPI schema and a contract test | CI job fails on undocumented routes |
| Every event has a JSON Schema in packages/contracts and a changelog entry | Schema registry compatibility check in CI |
| Every prompt file has a version, an owner and at least one eval case | Eval harness refuses to run an unregistered prompt |
| Every table with tenant data has tenant_id and an RLS policy | Migration lint script |
| Conventional commits; squash merge; PR template with risk and rollback sections | GitHub branch protection |
| Type checking is strict on both sides | mypy --strict, tsc --strict |
| Test coverage floor 80% on domain and application layers | pytest-cov gate |
| Secrets never in the repo | gitleaks pre-commit and CI |

## Where to read more in the guide

- Section 5: high-level design and the two core flows
- Section 7: low-level design per service (owns, consumes, emits, failure handling)
- Section 8: AI and ML layer, RAG design, eval thresholds
- Section 10: public API v1 and webhooks
- Section 12: tech stack (Python 3.12 + FastAPI, Next.js 15, Postgres + pgvector, Kafka, Temporal; uv workspaces, pnpm + Turborepo)
- Section 13: this structure and the conventions above
- Section 14: teams, contracts and decision rights
- Section 15: internal tools under /admin
- Section 17: environments, CI pipeline, release process
- Section 19: testing and quality strategy
- Section 20: phased roadmap
- Section 21: risks, open questions, decision log (ADRs in `docs/adr/`)

## Phase 0 next steps (deliberately not part of this scaffold)

- Root `pyproject.toml` (uv workspace), `pnpm-workspace.yaml`, `turbo.json`
- The service template: `pyproject.toml`, `Dockerfile`, `src/<package>/main.py`, Alembic init, `__init__.py` files
- `apps/web` via `create-next-app`, `apps/whatsapp-bot` and `packages/ui` via their own tooling
- CI workflows in `.github/workflows/` implementing the conventions table
- Terraform staging cluster, Keycloak, LLM gateway skeleton with cost ledger, Ontology v0 (about 15 GST attributes), domain kernel
- Full text for ADR-001 to ADR-006
