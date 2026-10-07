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
