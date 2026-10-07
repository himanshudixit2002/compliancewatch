-- One login role per service schema, cw_<schema>, for that service's processes: make run, make
-- worker, make relay, make seed and make web-stack STORE=postgres on the dev stack, and each
-- service's CW_DATABASE_URL in a deployment (infra/deploy/README.md). The combined product keeps
-- cw_app (50-app-role.sql, make product-role), one role for the one process that hosts them all.
--
-- Plain SQL, safe to repeat, run as the role that owns the schemas and runs the migrations:
-- $POSTGRES_USER on the dev stack (make db-roles, and the postgres image on a fresh volume, where
-- it runs after init.sql), the schemas' owner in a deployment. It sets no password:
-- dev-passwords.sql gives the dev stack's placeholders, and a deployment sets each password from
-- its secret store.
--
-- Each role is a login and nothing more: not a superuser, no row-level security bypass, no
-- database or role creation, no replication, NOINHERIT. The tenant policies therefore apply to it
-- as they do in a deployment. It gets:
--   - USAGE on its own schema and on public (pgvector's types and functions);
--   - SELECT, INSERT, UPDATE and DELETE on every table of its schema (the outbox, the consumer
--     inbox, the idempotency keys and the routing directories included) and USAGE and SELECT on
--     its sequences, now and on what later migrations by this owner create (default privileges);
--   - no write on <schema>.alembic_version, which only the migrations change;
--   - USAGE on audit and INSERT on its tables (audit.event, py_common.audit.writer); only
--     cw_identity also reads them, for the audit trail route.
-- No role gets another service's schema: the services call each other over HTTP.
--
-- A schema that does not exist yet is skipped with a notice; run the file again once it does.
-- The default privileges also reach the alembic_version table a schema's first migration creates,
-- so run the file again after that migration too: make migrate and make dev do, and so does a
-- deployment after a release that adds a schema.

DO $roles$
DECLARE
  service_schemas CONSTANT text[] := ARRAY[
    'identity', 'profile', 'rulebook', 'applicability', 'obligation',
    'notification', 'qa', 'llm_gateway', 'eval', 'pipeline'
  ];
  audit_schema CONSTANT text := 'audit';
  audit_reader CONSTANT text := 'cw_identity';
  owner_name CONSTANT text := current_user;
  schema_name text;
  role_name text;
  found_role record;
BEGIN
  FOREACH schema_name IN ARRAY service_schemas LOOP
    role_name := 'cw_' || schema_name;

    SELECT * INTO found_role FROM pg_roles WHERE rolname = role_name;
    IF NOT FOUND THEN
      EXECUTE format(
        'CREATE ROLE %I LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT '
        'NOREPLICATION',
        role_name
      );
    ELSE
      -- A role made by hand, or by an older copy of this file, loses every attribute but LOGIN.
      -- Only an attribute that differs is altered: SUPERUSER, BYPASSRLS and REPLICATION need a
      -- superuser to change, which a deployment's owner is not, so a role holding one stops this
      -- file with an error rather than keep it.
      IF found_role.rolsuper THEN
        EXECUTE format('ALTER ROLE %I NOSUPERUSER', role_name);
      END IF;
      IF found_role.rolbypassrls THEN
        EXECUTE format('ALTER ROLE %I NOBYPASSRLS', role_name);
      END IF;
      IF found_role.rolreplication THEN
        EXECUTE format('ALTER ROLE %I NOREPLICATION', role_name);
      END IF;
      IF found_role.rolcreatedb THEN
        EXECUTE format('ALTER ROLE %I NOCREATEDB', role_name);
      END IF;
      IF found_role.rolcreaterole THEN
        EXECUTE format('ALTER ROLE %I NOCREATEROLE', role_name);
      END IF;
      IF found_role.rolinherit THEN
        EXECUTE format('ALTER ROLE %I NOINHERIT', role_name);
      END IF;
      IF NOT found_role.rolcanlogin THEN
        EXECUTE format('ALTER ROLE %I LOGIN', role_name);
      END IF;
    END IF;

    -- PUBLIC may connect and use public unless a hardened database revoked it; grant both where
    -- this owner can (it owns the database and public on the dev stack).
    IF has_database_privilege(current_database(), 'CONNECT WITH GRANT OPTION') THEN
      EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), role_name);
    END IF;
    IF has_schema_privilege('public', 'USAGE WITH GRANT OPTION') THEN
      EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', role_name);
    END IF;

    IF to_regnamespace(quote_ident(schema_name)) IS NULL THEN
      RAISE NOTICE 'schema % does not exist yet: % gets nothing on it until this file runs again',
        schema_name, role_name;
      CONTINUE;
    END IF;
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', schema_name, role_name);
    EXECUTE format(
      'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO %I',
      schema_name, role_name
    );
    EXECUTE format(
      'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I', schema_name, role_name
    );
    EXECUTE format(
      'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I '
      'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
      owner_name, schema_name, role_name
    );
    EXECUTE format(
      'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT USAGE, SELECT ON SEQUENCES TO %I',
      owner_name, schema_name, role_name
    );
    IF to_regclass(format('%I.alembic_version', schema_name)) IS NOT NULL THEN
      EXECUTE format(
        'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON %I.alembic_version FROM %I',
        schema_name, role_name
      );
    END IF;
  END LOOP;

  IF to_regnamespace(quote_ident(audit_schema)) IS NULL THEN
    RAISE NOTICE 'schema % does not exist yet: no role may write the audit log until this file '
      'runs again', audit_schema;
    RETURN;
  END IF;
  FOREACH schema_name IN ARRAY service_schemas LOOP
    role_name := 'cw_' || schema_name;
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', audit_schema, role_name);
    EXECUTE format('GRANT INSERT ON ALL TABLES IN SCHEMA %I TO %I', audit_schema, role_name);
    EXECUTE format(
      'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT INSERT ON TABLES TO %I',
      owner_name, audit_schema, role_name
    );
  END LOOP;
  EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO %I', audit_schema, audit_reader);
  EXECUTE format(
    'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT ON TABLES TO %I',
    owner_name, audit_schema, audit_reader
  );
END
$roles$;

-- The identity directory: one NOLOGIN role, cw_identity_directory, that reads every tenant's
-- data_request rows, and only through identity.data_requests_open(), a SECURITY DEFINER function
-- it owns which answers counts per kind (open, and overdue: past the 30-day deadline and not
-- completed) and no row. Identity's forced row-level security hides other tenants' requests from
-- cw_identity and cw_app, so the DataRequestOverdue alert's gauges count through it. Only
-- cw_identity and cw_app (when it exists; make product-role grants it too) may EXECUTE it; PUBLIC
-- may not. The role holds USAGE on identity, SELECT on data_request and the read policy
-- data_request_directory, and nothing else; nobody logs in as it.
--
-- The owner running this file creates the function as the role: a superuser can, and a
-- deployment's owner (CREATEROLE, not a superuser) is made a member WITH INHERIT FALSE, SET TRUE.
-- It does not inherit the role's reads, but it may SET ROLE to it and then read every tenant's
-- requests through the policy, as the runbook's first step does. That is acceptable: the owner
-- owns identity's tables and could switch their row-level security off anyway. The role makes
-- the function, takes EXECUTE from PUBLIC and grants it to the callers while it still acts as the
-- function's owner: a non-superuser owner back in its own role holds neither the function nor a
-- grant option on it, so a REVOKE or GRANT it ran would only warn and change nothing. The role
-- gets CREATE on identity only while the function is (re)made. Until identity's migration 0010
-- has made data_request, the role is created and the rest skipped with a notice.
--
-- The function counts the open requests of each kind (neither completed nor, once offered and
-- past the deadline, expired) and the overdue ones: never answered (received) and past the
-- deadline (identity.domain.data_requests).
DO $directory$
DECLARE
  directory_role CONSTANT text := 'cw_identity_directory';
  callers CONSTANT text[] := ARRAY['cw_identity', 'cw_app'];
  owner_name CONSTANT text := current_user;
  found_role record;
  caller text;
BEGIN
  SELECT * INTO found_role FROM pg_roles WHERE rolname = directory_role;
  IF NOT FOUND THEN
    EXECUTE format(
      'CREATE ROLE %I NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT '
      'NOREPLICATION',
      directory_role
    );
  ELSE
    IF found_role.rolcanlogin THEN
      EXECUTE format('ALTER ROLE %I NOLOGIN', directory_role);
    END IF;
    IF found_role.rolsuper THEN
      EXECUTE format('ALTER ROLE %I NOSUPERUSER', directory_role);
    END IF;
    IF found_role.rolbypassrls THEN
      EXECUTE format('ALTER ROLE %I NOBYPASSRLS', directory_role);
    END IF;
    IF found_role.rolinherit THEN
      EXECUTE format('ALTER ROLE %I NOINHERIT', directory_role);
    END IF;
    IF found_role.rolcreatedb OR found_role.rolcreaterole OR found_role.rolreplication THEN
      EXECUTE format('ALTER ROLE %I NOCREATEDB NOCREATEROLE NOREPLICATION', directory_role);
    END IF;
  END IF;

  IF to_regclass('identity.data_request') IS NULL THEN
    RAISE NOTICE 'identity.data_request does not exist yet: % gets its function once this file '
      'runs after identity''s migrations', directory_role;
    RETURN;
  END IF;

  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = owner_name)
     AND NOT pg_has_role(owner_name, directory_role, 'SET') THEN
    EXECUTE format('GRANT %I TO %I WITH INHERIT FALSE, SET TRUE', directory_role, owner_name);
  END IF;
  EXECUTE format('GRANT USAGE ON SCHEMA identity TO %I', directory_role);
  EXECUTE format('GRANT SELECT ON identity.data_request TO %I', directory_role);
  IF NOT EXISTS (
    SELECT FROM pg_policies
     WHERE schemaname = 'identity' AND tablename = 'data_request'
       AND policyname = 'data_request_directory'
  ) THEN
    EXECUTE format(
      'CREATE POLICY data_request_directory ON identity.data_request FOR SELECT TO %I '
      'USING (true)',
      directory_role
    );
  END IF;

  IF to_regprocedure('identity.data_requests_open()') IS NOT NULL
     AND (SELECT proowner::regrole::text FROM pg_proc
           WHERE oid = to_regprocedure('identity.data_requests_open()')) <> directory_role THEN
    EXECUTE 'DROP FUNCTION identity.data_requests_open()';
  END IF;
  EXECUTE format('GRANT CREATE ON SCHEMA identity TO %I', directory_role);
  EXECUTE format('SET LOCAL ROLE %I', directory_role);
  EXECUTE $function$
    CREATE OR REPLACE FUNCTION identity.data_requests_open()
    RETURNS TABLE (kind text, open bigint, overdue bigint)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $body$
      SELECT r.kind::text,
             count(*),
             count(*) FILTER (WHERE r.status = 'received' AND r.deadline_at < now())
        FROM identity.data_request AS r
       WHERE r.status = 'received' AND r.deadline_at < now()
          OR r.status <> 'completed' AND r.deadline_at >= now()
       GROUP BY r.kind
    $body$
  $function$;
  EXECUTE 'REVOKE ALL ON FUNCTION identity.data_requests_open() FROM PUBLIC';
  FOREACH caller IN ARRAY callers LOOP
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = caller) THEN
      EXECUTE format(
        'GRANT EXECUTE ON FUNCTION identity.data_requests_open() TO %I', caller
      );
    END IF;
  END LOOP;
  EXECUTE format('SET LOCAL ROLE %I', owner_name);
  EXECUTE format('REVOKE CREATE ON SCHEMA identity FROM %I', directory_role);
END
$directory$;
