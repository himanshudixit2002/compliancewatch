# rulebook service

Part of the ComplianceWatch monorepo. Health routes, alembic wiring and the knowledge schema
(models plus one migration); no domain code, repositories or read API yet.
Design reference: Project Foundation guide, sections 7, 8, 9 and 14; Architecture Reference 3.2 and 5.2.

- **Owns:** Rules, RuleVersions, Clauses, embeddings; versioning, supersession graph, hybrid search index, as-of queries;
  the knowledge tables `canonical_entity`, `clause_entity` and `rule_relation` (aligned entities,
  clause mentions, typed relations between rule versions and entities)
- **Owning team:** Regulatory Intelligence
- **Consumes:** rule.published; rulebook read API (served to the engine, Q&A and review service)
- **Emits / publishes:** rule.superseded (scheduled when effective dates pass)

## What is in the database today

Migration `0001` creates three tables in schema `rulebook`:

| Table | Purpose | Keys |
| --- | --- | --- |
| `canonical_entity` | One row per aligned entity: `type` (ten values), `canonical_name`, `aliases text[]` | pk `id`; unique (`type`, `canonical_name`); GIN index on `aliases` |
| `clause_entity` | A mention of an entity in a clause with its character span | pk (`clause_id`, `entity_id`, `span_start`); fk `entity_id` to `canonical_entity` (restrict) |
| `rule_relation` | A typed relation (`supersedes`, `amends`, `refers_to`, `exempts`, `extends_deadline`, `corrects`, `withdraws`) from a rule version to a rule version or an entity, with the evidence clause | pk `id`; unique (`from_rule_version_id`, `relation`, `to_kind`, `to_ref`, `clause_id`); indexes (`relation`, `to_ref`) and (`from_rule_version_id`); fk `to_entity_id` to `canonical_entity` (restrict); CHECKs `ck_rule_relation_pairing`, `ck_rule_relation_target_entity`, `ck_rule_relation_not_self` |

The `clause`, `rule` and `rule_version` tables are not there yet. `clause_id` and
`from_rule_version_id` are plain uuid columns; the migration that creates those tables adds the
foreign keys. The vocabulary in the CHECK constraints is derived from `domain_kernel.knowledge`
(`EntityType`, `RelationKind`, `RULE_VERSION_KIND`), and `to_kind` is `rule_version` or one of the
ten entity types. Three more CHECKs on `rule_relation` repeat the kernel's rules:
`ck_rule_relation_pairing` (`supersedes`, `extends_deadline`, `corrects` and `withdraws` target a rule version),
`ck_rule_relation_target_entity` (`to_entity_id` is set exactly when `to_kind` is an entity type)
and `ck_rule_relation_not_self` (`to_ref` is never the source rule version). Table names are
unqualified: the connection's `search_path` puts them in `rulebook`.

## Layout

```
src/rulebook/
  api/             # routers, request/response schemas, auth dependencies
  application/     # use cases, event handlers, unit of work
  domain/          # entities, value objects, domain events, repository protocols
  infrastructure/  # SQLAlchemy models (models.py: Base and the three knowledge rows), repositories, Kafka, adapters
  main.py          # composition root: create_app(...) from py-common
migrations/        # alembic; env.py reads CW_DATABASE_URL and CW_DB_SCHEMA and targets models.Base.metadata
  versions/20260928_0001_knowledge_schema.py   # hand-written, mirrors models.py
tests/
  unit/            # domain and application with fakes; no I/O. test_models_vocabulary.py: model CHECKs against the kernel enums
  integration/     # testcontainers (pgvector image): test_knowledge_schema.py runs the migration up, down and up
  contract/        # provider-side contract tests for this service's API and events
alembic.ini, pyproject.toml, Dockerfile
```

## How to run

From the repo root:

```bash
make dev                          # infrastructure (Docker Compose)
make migrate SERVICE=rulebook     # alembic upgrade head in schema rulebook
make run SERVICE=rulebook         # http://localhost:8003/health, /ready, /v1/rulebook/ping
make test                         # unit + contract tests with the coverage gate
make py-test-integration          # testcontainers tests; needs Docker
uv run pytest services/rulebook/tests/integration -q -m integration   # this service only
docker build -f services/rulebook/Dockerfile -t compliancewatch-rulebook .
```

With Colima, export `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock` before the
integration tests: the testcontainers reaper mounts the daemon socket at its path inside the VM,
not the host path `~/.colima/default/docker.sock`.

Check the schema after `make migrate`:

```bash
docker compose exec -T postgres psql -U cw -d compliancewatch -Atc \
  "select table_name from information_schema.tables where table_schema='rulebook' order by 1"
# alembic_version, canonical_entity, clause_entity, rule_relation
docker compose exec -T postgres psql -U cw -d compliancewatch -Atc \
  "select conname from pg_constraint where conrelid = 'rulebook.rule_relation'::regclass order by 1"
# ck_rule_relation_not_self, ck_rule_relation_pairing, ck_rule_relation_relation, ck_rule_relation_target_entity,
# ck_rule_relation_to_kind, fk_rule_relation_to_entity_id_canonical_entity, pk_rule_relation, uq_rule_relation_edge
```

Roll back with `CW_DATABASE_URL=... CW_DB_SCHEMA=rulebook uv run --package compliancewatch-rulebook alembic -c services/rulebook/alembic.ini downgrade base`
(the URL `make migrate` builds, with `?options=-csearch_path%3Drulebook%2Cpublic`).

Package `rulebook`, dev port 8003, Postgres schema `rulebook`. Details: [docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).
