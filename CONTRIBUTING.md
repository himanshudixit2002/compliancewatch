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
make check       # the CI gates that need no Docker (listed under Pull requests)
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
  on `main`, with no body (the repository settings in
  [docs/onboarding/repository-settings.md](docs/onboarding/repository-settings.md)).

## Pull requests

The template in `.github/PULL_REQUEST_TEMPLATE.md` asks for four things; fill all of them:

- Summary: what changed and why, in plain sentences.
- Risk: what could break, who notices, and how.
- Rollback: how the change is undone (revert, flag, migration downgrade).
- Test evidence: the commands you ran and their results. Integration tests need Docker; say
  whether you ran them.

A merge into `main` needs one CI check, `CI gate`, plus the two pr-checks jobs. The gate needs
every other job in `.github/workflows/ci.yml` and passes only when each one succeeded or was
skipped by its path filter. The jobs, and what runs them locally:

| CI job | Checks | Locally |
| --- | --- | --- |
| python | ruff, mypy in strict mode, import-linter, pytest with an 80% coverage floor on the domain and application layers, lockfile current, a committed OpenAPI spec for every service with API routes | `make check` |
| typescript | prettier, eslint, tsc, vitest, build | `make check` |
| contracts | event schemas, a schema for every event topic in code, generated clients in sync, event and OpenAPI compatibility with the base branch | `make check`, `make openapi-compat BASE=origin/main` |
| evals | golden cases well formed, the eval harness with the scripted and fake providers | `make eval` |
| integration | testcontainers tests of the packages the change touches | `make py-test-integration` |
| ops | runbook links, migration files, the CI gate's needs, promtool rules and their tests, actionlint | `make check`, `make alerts-check`, `make ci-lint` |
| dev-stack | the compose stack, every migration, tenant tables under forced row-level security | `make dev && make migrate && make migrations-catalog` |
| sast | Semgrep registry packs and the rules in `.semgrep` | `make sast` |
| dependency-scan | Trivy: vulnerable dependencies with a fix and misconfigured Dockerfiles, HIGH and CRITICAL | `make deps-scan` |
| gitleaks | secrets in the branch's commits | the pre-commit hook |

`make check` covers every gate that needs no Docker: lint, typecheck, test, importlint,
lock-check, contracts-check, runbooks-check, migrations-check, openapi-check and ci-gate-check.
`make py-test-integration`, `make alerts-check`, `make migrations-catalog`, `make sast` and
`make deps-scan` need Docker. Every night, `nightly.yml` runs the evals against a real model,
repeats the Trivy scan against the day's advisories and runs the API property tests with 200
random examples per operation; a failure opens or updates the issue labelled `nightly-failure`.
A red check is fixed on the branch, not worked around.

A new gate is a Make target in its own section of the `Makefile` with a `CHECKS += <target>`
line when it belongs in `make check`. A new CI job goes above `gate` in ci.yml and into the
gate's `needs`; `make ci-gate-check` fails until it is there. Path filters are only appended to.

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

## Migrations

`make migrations-check` (part of `make check`) reads every `services/*/migrations/versions`:

- One head per service and unique revision ids, so two branches that both add `0002` fail. Files
  are named `YYYYMMDD_NNNN_slug.py` with `NNNN` equal to the revision.
- `downgrade()` undoes the upgrade. When it cannot, it says why with
  `# irreversible: <reason>`.
- Expand first, contract later: dropping or renaming a table or column, or making a column NOT
  NULL, carries `# contract: <reason>` on the line above, and lands in a release after the code
  that stopped reading the old shape.

After `make dev && make migrate`, `make migrations-catalog` reads the migrated database. A table
with tenant data has a NOT NULL `tenant_id`, row-level security enabled and forced, and a policy
for ALL commands whose USING and WITH CHECK compare `tenant_id` with
`NULLIF(current_setting('app.tenant_id', true), '')`; every table in a tenant schema has
`tenant_id`. A table that cannot follow this rule gets an exemption in
`infra/scripts/migration_lint.toml` in the same pull request as its migration, with the reason
the report prints. Exemptions are append-only, and one that matches no table fails. Kind
`routing_directory` is for a table whose reads cross tenants: every policy that admits a write
must still hold the tenant check.

## Adding an API route

1. `make openapi SERVICE=<name>` rewrites `packages/contracts/openapi/<name>.v1.json`; the
   service's `tests/contract/test_openapi.py` fails until the committed spec matches what it
   serves. `make openapi-check` fails for a service that serves routes beyond health, ready and
   ping without a committed spec and that test.
2. The contracts job compares the specs with the base branch (`make openapi-compat
   BASE=origin/main` locally). A removed operation or response, a newly required field or
   parameter, a narrowed enum or a changed type is a break. A deliberate break needs an ADR and a
   new row in `packages/contracts/openapi/BREAKING.md`.
3. Opt the operation in to the schemathesis property tests: add `"METHOD /path"` to `OPERATIONS`
   in the service's `tests/contract/test_api_properties.py`. Each operation gets 25
   derandomized examples in CI and 200 random ones nightly (`HYPOTHESIS_PROFILE=nightly uv run
   pytest -m contract`). A finding is fixed in the service; an operation that needs a redesign
   first goes into `EXCLUDED` with the reason.
4. A route for clients outside the platform is public: tag it `public`, list the roles that may
   call it in `openapi_extra={"x-roles": [...]}` and declare its problem responses. A POST that
   creates takes `IdempotencyKey` and `run_idempotent` (`py_common.idempotency`); a list takes
   `Pagination` and answers `Page[T]` (`py_common.pagination`). `make openapi-public` rebuilds
   `packages/contracts/openapi/public.v1.json` and the Python REST models, and fails on a public
   route that breaks one of these rules. Bump the version in `public.meta.json` with a section
   in `openapi/CHANGELOG.md`; `make contracts-check` fails while the committed files are stale.

## Adding a feature flag

A setting that switches behaviour is a flag: a bool named `*_enabled`, a name ending in
`_provider`, `_mode` or `_backend`, or a field listed in `SWITCH_FIELDS` in
`infra/scripts/check_flags.py`. Register it in `packages/flags/registry.json` in the same pull
request, with its owner, a default that is off, a removal condition and an expiry date, then run
`make flags`, which rewrites py-common's copy. `make flags-check`, part of `make check`, fails on
a switch without an entry, a bool default of true, a date that has passed or a stale copy. Any
other bool or `Literal` setting is configuration and goes in `NOT_FLAGS` with the reason.
`packages/flags/README.md` has the fields and the env and Unleash providers.

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

`make contracts-check` finds every event class that sets `topic` and fails when its schema is
missing or its `x-version` differs from the class's `schema_version`. A topic that is only logged
for now is listed with its reason in `LOG_ONLY_TOPICS` in
`packages/contracts/scripts/check_topics.py`; the commit that adds its schema removes the entry.

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

## Security scans

`make sast` runs Semgrep's registry packs for Python, TypeScript, Dockerfiles and GitHub Actions
and the repository's own rules in `.semgrep/cw.yml` (SQL built by string formatting in a
service, a secret compared with `==`, TLS verification turned off, `yaml.load` without
`SafeLoader`), then the rules' test cases in `.semgrep/cw.py`. A finding of severity ERROR
fails. Fix it; when it is a false positive, put `# nosemgrep: <rule-id>` on the line with a
comment that says why. A new local rule comes with `# ruleid:` and `# ok:` cases in `cw.py`.

`make deps-scan` runs Trivy with `.trivy.yaml`: vulnerable dependencies in `uv.lock` and
`pnpm-lock.yaml` and misconfigured Dockerfiles, HIGH and CRITICAL, only where a fix exists.
Bump the dependency or change the Dockerfile. When that is not possible yet, add an entry to
`.trivyignore.yaml` with a `statement` (why the finding is acceptable) and an `expired_at` date
at most 90 days out; a test in `make check` refuses an entry without them, and Trivy reports the
finding again once the date passes.

Both scans run in CI and report to code scanning. Dependabot opens weekly pull requests for uv,
npm, GitHub Actions and Docker base images, minor and patch releases grouped per ecosystem.

## Security

See [SECURITY.md](SECURITY.md) for reporting: GitHub private vulnerability reporting, from the
repository's Security tab. Never paste a real secret into the repository, an issue or a pull
request.
