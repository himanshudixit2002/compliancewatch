-- The role the local product's services connect as (make product): it owns nothing and is not a
-- superuser, so row-level security applies to it as it does in a deployment. make migrate, make
-- run and make web-stack connect as $POSTGRES_USER, the image's superuser, which bypasses every
-- policy (docs/onboarding/local-dev.md, "Row-level security in the dev stack").
--
-- make product runs this through psql on the running stack with the variables app_user and
-- app_password, after make migrate; it is safe to repeat. It creates the role when missing, and
-- grants it the use of every service schema and every table and sequence in them, now and as
-- later migrations (run as the superuser) create more. No compose file mounts it, so a fresh
-- volume gets the role from the first make product.
\set ON_ERROR_STOP on

SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE',
  :'app_user', :'app_password'
)
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app_user') \gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'app_user') \gexec

SELECT format('GRANT USAGE ON SCHEMA %I TO %I', nspname, :'app_user'),
       format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO %I',
              nspname, :'app_user'),
       format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I', nspname, :'app_user'),
       format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I '
              'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
              current_user, nspname, :'app_user'),
       format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I '
              'GRANT USAGE, SELECT ON SEQUENCES TO %I',
              current_user, nspname, :'app_user')
FROM pg_namespace
WHERE nspname IN ('identity', 'profile', 'rulebook', 'applicability', 'obligation',
                  'notification', 'qa', 'llm_gateway', 'eval', 'pipeline', 'audit') \gexec
