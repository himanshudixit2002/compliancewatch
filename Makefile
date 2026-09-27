# ComplianceWatch root Makefile. Phase 0 scaffold: every target is a stub.
# Guide section 13: make dev, make test, make eval, make migrate

.PHONY: dev test eval migrate

dev:       ## Local stack via Docker Compose (Postgres, Redis, Redpanda, Temporal, Langfuse, fake LLM provider) - guide section 17
	@echo "make dev: not implemented yet"

test:      ## Lint, type-check, unit / integration / contract tests, affected-only - guide section 19
	@echo "make test: not implemented yet"

eval:      ## Eval harness against evals/golden with the section 8 thresholds
	@echo "make eval: not implemented yet"

migrate:   ## Alembic migrations for every service, expand-first - guide section 17
	@echo "make migrate: not implemented yet"
