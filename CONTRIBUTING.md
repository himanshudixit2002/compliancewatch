# Contributing

This is a private repository; these notes exist so that anyone working in it, including the
maintainer six months from now, follows the same rules.

## Set up

Follow [docs/onboarding/local-dev.md](docs/onboarding/local-dev.md). In short: install uv,
pnpm and Colima (or another Docker engine), then from the repo root:

```bash
make install     # uv sync + pnpm install
make hooks       # pre-commit and commit-msg hooks
make dev         # Postgres, Redis, Redpanda, Temporal
make migrate     # every service's migrations
make check       # what CI runs: lint, typecheck, tests, import-linter, lock check
```

`make check` must pass before a pull request is opened, and it must stay green afterwards.

## Branches and commits

- Branch names are short and descriptive, in kebab-case: `llm-gateway-skeleton`,
  `kag-knowledge-schema`. No personal prefixes, no ticket numbers.
- Commits follow Conventional Commits with a short, lowercase subject and no body unless a fact
  has to be recorded: `feat(rulebook): knowledge schema migration`, `docs: adr 012 to 014`.
  Types: feat, fix, docs, chore, refactor, test, ci, build, perf, revert, style. The commit-msg
  hook rejects anything else.
- Never force-push a shared branch, never amend a pushed commit, never commit `.env` or any
  real credential.
- Pull requests are squash-merged. The title follows the commit rules and becomes the commit
  on `main`.

## Pull requests

The template in `.github/PULL_REQUEST_TEMPLATE.md` asks for four things; fill all of them:

- Summary: what changed and why, in plain sentences.
- Risk: what could break, who notices, and how.
- Rollback: how the change is undone (revert, flag, migration downgrade).
- Test evidence: the commands you ran and their results. Integration tests need Docker; say
  whether you ran them.

CI runs ruff, mypy in strict mode, import-linter, pytest with an 80% coverage floor on the
domain and application layers, the TypeScript lint, typecheck, tests and build, a compose
smoke test with every migration, and gitleaks. A red check is fixed on the branch, not
worked around.

## Layering rules

Every Python service has the same four layers: `api`, `application`, `domain`,
`infrastructure`. The domain imports only the standard library and `domain_kernel`; the
application layer knows nothing about HTTP or persistence; infrastructure implements the
domain's protocols; `main.py` wires them. Services never import each other. import-linter
enforces all of this in `make check`.

## Adding a service

1. Copy the shape of an existing service such as `services/obligation`: `pyproject.toml`,
   `Dockerfile`, `alembic.ini`, `migrations/`, `src/<package>/{api,application,domain,infrastructure}`,
   `main.py`, `tests/{unit,integration,contract}`.
2. Register it: `SERVICES` and, if the package or schema name differs from the directory, the
   `PKG_*` / `SCHEMA_*` / `PORT_*` variables in the `Makefile`; the schema in
   `infra/dev/postgres/init.sql`; the owner line in `CODEOWNERS`; the container in
   `root_packages` and the layer contracts of the root `pyproject.toml`.
3. Run `uv lock`, then `make check` and `make migrate SERVICE=<name>`.

## Adding a source adapter

An adapter implements the kernel's `SourceAdapter` protocol (`list_documents`, `fetch`) in
`services/pipeline/adapters/`. Every adapter ships with recorded fixtures (the fetched pages
and files) under the pipeline's `tests/fixtures/` so its tests never touch the network, and
with a conformance test that runs the same checks as the other adapters. Adapters identify
themselves with a user agent, respect `robots.txt`, rate-limit politely, and store the raw
file, its SHA-256, the fetch time and the source URL. The adapter registry arrives with the
first adapters; until then this section describes the rule, not existing code.

## Adding an event

Events are contracts: a JSON Schema in `packages/contracts/events/schemas/<topic>.v1.json`
with `x-version`, `x-producer` and `x-tenant-scoped`, at least one golden message under
`events/examples/<topic>/`, and a line in `events/CHANGELOG.md`. Then:

1. `make contracts` regenerates the Python and TypeScript clients; commit them with the schema.
2. Declare the producer's event class in its service domain with `topic` and `schema_version`
   matching the schema, and write it with `py_common.outbox.OutboxWriter` on the connection
   that holds the state change. The service's migration creates the table with
   `create_outbox_table(op)`.
3. Consumers use `IdempotentConsumer` and `create_processed_event_table(op)`.

Adding an optional field is a minor bump. Removing or renaming a field, adding a required one or
narrowing an enum is breaking: a new `v2` file next to the old one and an ADR. CI replays the
base branch's examples against your schemas and asks the Redpanda schema registry; both must
pass. `packages/contracts/README.md` has the full rules.

## Adding a prompt

Prompts are versioned files with an owner and at least one eval case. The gateway refuses a
prompt reference that is not in `services/llm-gateway/prompts/registry.toml`, so:

1. Add the prompt file next to the code that uses it (`services/pipeline/prompts/` for the
   extraction pipeline).
2. Register it: name, version, owner, `eval_cases >= 1`, and the file's SHA-256 in
   `registry.toml`.
3. Add the eval case under `evals/golden/`.
4. Call it through the gateway with `prompt = "<name>@<version>"`. Tests use the fake
   provider; no test calls a real model.

A prompt change is a new version and a pull request that runs the eval suite.

## Writing style

Code comments, docstrings, READMEs and pull requests are plain engineering prose: short
sentences, no roadmap labels in code, no marketing words, no emoji. A README may cite the
design guide once; code does not. Do not claim accuracy or performance without an eval or a
benchmark behind the number.

## Security

See [SECURITY.md](SECURITY.md) for reporting. Never paste a real secret into the repository,
an issue or a pull request.
