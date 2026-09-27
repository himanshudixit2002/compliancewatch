# ADR-001: Monorepo with one directory per service and a shared contracts package

- **Status:** Accepted
- **Date:** 2026-09-27
- **Deciders:** Platform and Infrastructure, with every service-owning team

## Context

The system is thirteen logical services (ten service directories today), two TypeScript apps and
a handful of shared packages: contracts (OpenAPI and event schemas), the domain kernel, the
ontology, py-common and the UI kit. Services talk to each other only through those contracts.
Most changes in the first year will touch a contract and both sides of it: a new event field, a
new ontology attribute, a regenerated client. With one repository per service that is several
pull requests that must land in order, and CI can never test the combination. The team is small,
two combined teams now and five later, and ownership is by directory, not by repository.

## Decision

One repository. Each service lives under `services/`, each app under `apps/`, shared code under
`packages/`, with `packages/contracts` as the package every service builds against. `CODEOWNERS`
maps each directory to one owning team; a change to a contract needs a review from every team
that consumes it, a change inside a service needs only its owner. uv workspaces manage the Python
side and pnpm with Turborepo the TypeScript side; one CI workflow runs the affected side through
path filters, and `make check` runs the same gates locally. Nx and Bazel were considered and set
aside as heavier than two package managers need; a polyrepo with published contract packages was
set aside because it makes the common change slow and untestable as a whole.

## Consequences

- A contract and all of its consumers change in one pull request, reviewed by each consumer's
  owner, and CI verifies the combination before merge.
- One copy of every tool configuration (ruff, mypy, eslint, prettier, pre-commit); services
  cannot drift from each other.
- Services still build and deploy separately: one image and one Helm chart each. The shared
  repository does not mean a shared release.
- CI must stay path-filtered and cached as the repository grows. Turborepo caches the TypeScript
  side; the Python side runs the whole workspace today and will need affected-only runs once
  services carry real code.
- Directory ownership needs GitHub teams. Until they exist, every `CODEOWNERS` line names one
  person and records the intended team in a comment.
- Revisit if a team needs a release cadence the shared main branch cannot give, or if CI for an
  unrelated change regularly takes longer than about fifteen minutes.
