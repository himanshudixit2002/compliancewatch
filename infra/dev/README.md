# infra/dev

Assets for the Docker Compose development stack defined in the root `docker-compose.yml`
(guide section 17, "dev" environment). Owned by Platform and Infrastructure.

- `postgres/init.sql`: runs once on an empty `postgres_data` volume; creates the `vector`
  extension, one schema per service, and the `temporal`, `temporal_visibility` and `langfuse`
  databases. To re-run it: `make dev-reset`.
- `temporal/dynamicconfig/development-sql.yaml`: dynamic config for the local Temporal server.

Cluster environments never use these files: schemas come from migrations and Helm jobs. See
`docs/onboarding/local-dev.md`.
