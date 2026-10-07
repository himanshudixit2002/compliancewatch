-- The role the local product's services connect as (make product): it owns nothing and is not a
-- superuser, so row-level security applies to it as it does in a deployment. The product hosts
-- every service in one process, so this one role has every service schema; the separate
-- processes of make run and make web-stack STORE=postgres connect as each service's own role
-- (roles.sql), and make migrate as $POSTGRES_USER, the schemas' owner
-- (docs/onboarding/local-dev.md, "Database roles and row-level security").
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

-- The count of every tenant's open data requests (roles.sql, the identity directory), once
-- identity's migrations and make db-roles have made it. Granted as the function's owner,
-- cw_identity_directory: an owner that is not a superuser holds no grant option on it in its own
-- role (roles.sql made it a member WITH INHERIT FALSE, SET TRUE), so its own GRANT would only
-- warn. The three statements run in order, the role reset last.
SELECT statement
FROM unnest(ARRAY[
       'SET ROLE cw_identity_directory',
       format('GRANT EXECUTE ON FUNCTION identity.data_requests_open() TO %I', :'app_user'),
       'RESET ROLE'
     ]) WITH ORDINALITY AS steps(statement, step)
WHERE to_regprocedure('identity.data_requests_open()') IS NOT NULL
ORDER BY step \gexec
