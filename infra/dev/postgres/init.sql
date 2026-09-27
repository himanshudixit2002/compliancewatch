-- Executed once by the postgres image entrypoint (docker-entrypoint-initdb.d) on a fresh volume,
-- as superuser $POSTGRES_USER connected to $POSTGRES_DB. Editing this file does nothing for an
-- existing volume: run `make dev-reset`. Cluster environments create schemas through migrations
-- and Helm jobs, never through this file (guide section 17).
\set ON_ERROR_STOP on

-- Sidecar databases for infrastructure that keeps its state in the same cluster (guide section 9:
-- Temporal and Langfuse self-hosted with state in Postgres). Temporal runs with SKIP_DB_CREATE=true.
SELECT 'CREATE DATABASE temporal'            WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'temporal') \gexec
SELECT 'CREATE DATABASE temporal_visibility' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'temporal_visibility') \gexec
SELECT 'CREATE DATABASE langfuse'            WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse') \gexec

-- Application database: pgvector once, in public; services keep public on their search_path so
-- the `vector` type resolves unqualified. Then one schema per service (guide sections 7 and 9).
-- Section 9's logical prefixes regulatory.* / business.* / work.* map onto these per-service
-- schemas in each service's first migrations; only `audit` is kept literally.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS identity;       -- services/identity
CREATE SCHEMA IF NOT EXISTS profile;        -- services/profile (package profile_service)
CREATE SCHEMA IF NOT EXISTS rulebook;       -- services/rulebook
CREATE SCHEMA IF NOT EXISTS applicability;  -- services/applicability-engine
CREATE SCHEMA IF NOT EXISTS obligation;     -- services/obligation
CREATE SCHEMA IF NOT EXISTS notification;   -- services/notification
CREATE SCHEMA IF NOT EXISTS qa;             -- services/qa
CREATE SCHEMA IF NOT EXISTS llm_gateway;    -- services/llm-gateway
CREATE SCHEMA IF NOT EXISTS eval;           -- services/eval (package eval_service)
CREATE SCHEMA IF NOT EXISTS pipeline;       -- services/pipeline
CREATE SCHEMA IF NOT EXISTS audit;          -- audit.event, append-only (guide section 9); written via py-common
