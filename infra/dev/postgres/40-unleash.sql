-- The Unleash server's own database (compose profile "flags", CW_FLAGS_PROVIDER=unleash). Run by
-- the postgres image on a fresh volume, after init.sql, and by `make dev-flags` on an existing
-- one; both are safe to repeat.
\set ON_ERROR_STOP on

SELECT 'CREATE DATABASE unleash' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'unleash') \gexec
