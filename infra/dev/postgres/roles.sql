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

-- The identity directory: one NOLOGIN role, cw_identity_directory, that reads across tenants
-- only through the SECURITY DEFINER functions it owns, each answering the listed columns and
-- nothing else. Identity's forced row-level security hides other tenants' rows from cw_identity
-- and cw_app, so these reads go through the role:
--   - identity.data_requests_open(): counts per kind of every tenant's open data requests (open,
--     and overdue: past the 30-day deadline and not completed), no row; the DataRequestOverdue
--     alert's gauges read it.
--   - identity.tenant_directory(q, after, lim, only_id): the admin tenant list (GET
--     /v1/identity/admin/tenants): id, kind, name, status, when the tenant was created, the plan
--     key and status of its newest subscription ('' without one), and how many users it has, how
--     many of them active; never a token, an email address or a phone number. Tenants whose name
--     contains q (any case), or whose id is q, in the order of (name, id), at most lim of them
--     after the tenant `after` names; `only_id` reads one tenant.
-- Only cw_identity and cw_app (when it exists; make product-role grants it too) may EXECUTE them;
-- PUBLIC may not. The role holds USAGE on identity, SELECT on data_request, on the columns of
-- tenant, app_user and billing_subscription the functions read, and one read policy per table
-- (<table>_directory), and nothing else; nobody logs in as it.
--
-- The owner running this file creates the functions as the role: a superuser can, and a
-- deployment's owner (CREATEROLE, not a superuser) is made a member WITH INHERIT FALSE, SET TRUE.
-- It does not inherit the role's reads, but it may SET ROLE to it and then read every tenant's
-- rows through the policies, as the runbook's first step does. That is acceptable: the owner
-- owns identity's tables and could switch their row-level security off anyway. The role makes
-- each function, takes EXECUTE from PUBLIC and grants it to the callers while it still acts as the
-- function's owner: a non-superuser owner back in its own role holds neither the function nor a
-- grant option on it, so a REVOKE or GRANT it ran would only warn and change nothing. The role
-- gets CREATE on identity only while the functions are (re)made. Each function is made once the
-- tables it reads exist (identity's migrations 0003, 0008 and 0010); until then the role is
-- created and that function skipped with a notice.
--
-- data_requests_open() counts the open requests of each kind (neither completed nor, for an
-- export offered and past the deadline, expired) and the overdue ones past the deadline: an
-- export never answered (received), or a deletion not completed, which never expires
-- (identity.domain.data_requests).
DO $directory$
DECLARE
  directory_role CONSTANT text := 'cw_identity_directory';
  callers CONSTANT text[] := ARRAY['cw_identity', 'cw_app'];
  owner_name CONSTANT text := current_user;
  requests_function CONSTANT text := 'identity.data_requests_open()';
  tenants_function CONSTANT text := 'identity.tenant_directory(text, uuid, integer, uuid)';
  found_role record;
  caller text;
  have_requests boolean;
  have_tenants boolean;
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

  have_requests := to_regclass('identity.data_request') IS NOT NULL;
  have_tenants := to_regclass('identity.tenant') IS NOT NULL
    AND to_regclass('identity.app_user') IS NOT NULL
    AND to_regclass('identity.billing_subscription') IS NOT NULL;
  IF NOT have_requests AND NOT have_tenants THEN
    RAISE NOTICE 'identity''s tables do not exist yet: % gets its functions once this file runs '
      'after identity''s migrations', directory_role;
    RETURN;
  END IF;

  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = owner_name)
     AND NOT pg_has_role(owner_name, directory_role, 'SET') THEN
    EXECUTE format('GRANT %I TO %I WITH INHERIT FALSE, SET TRUE', directory_role, owner_name);
  END IF;
  EXECUTE format('GRANT USAGE ON SCHEMA identity TO %I', directory_role);
  IF have_requests THEN
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
  ELSE
    RAISE NOTICE 'identity.data_request does not exist yet: data_requests_open() is made once '
      'this file runs after identity''s migration 0010';
  END IF;
  IF have_tenants THEN
    EXECUTE format(
      'GRANT SELECT (id, kind, name, status, created_at) ON identity.tenant TO %I',
      directory_role
    );
    EXECUTE format('GRANT SELECT (tenant_id, status) ON identity.app_user TO %I', directory_role);
    EXECUTE format(
      'GRANT SELECT (tenant_id, plan_key, status, started_at, provider_subscription_id) '
      'ON identity.billing_subscription TO %I',
      directory_role
    );
    IF NOT EXISTS (
      SELECT FROM pg_policies
       WHERE schemaname = 'identity' AND tablename = 'tenant' AND policyname = 'tenant_directory'
    ) THEN
      EXECUTE format(
        'CREATE POLICY tenant_directory ON identity.tenant FOR SELECT TO %I USING (true)',
        directory_role
      );
    END IF;
    IF NOT EXISTS (
      SELECT FROM pg_policies
       WHERE schemaname = 'identity' AND tablename = 'app_user'
         AND policyname = 'app_user_directory'
    ) THEN
      EXECUTE format(
        'CREATE POLICY app_user_directory ON identity.app_user FOR SELECT TO %I USING (true)',
        directory_role
      );
    END IF;
    IF NOT EXISTS (
      SELECT FROM pg_policies
       WHERE schemaname = 'identity' AND tablename = 'billing_subscription'
         AND policyname = 'billing_subscription_directory'
    ) THEN
      EXECUTE format(
        'CREATE POLICY billing_subscription_directory ON identity.billing_subscription '
        'FOR SELECT TO %I USING (true)',
        directory_role
      );
    END IF;
  ELSE
    RAISE NOTICE 'identity''s tenant tables do not exist yet: tenant_directory() is made once '
      'this file runs after identity''s migrations 0003 and 0008';
  END IF;

  -- A function made by an older copy of this file as another role is dropped and made again.
  IF to_regprocedure(requests_function) IS NOT NULL
     AND (SELECT proowner::regrole::text FROM pg_proc
           WHERE oid = to_regprocedure(requests_function)) <> directory_role THEN
    EXECUTE 'DROP FUNCTION ' || requests_function;
  END IF;
  IF to_regprocedure(tenants_function) IS NOT NULL
     AND (SELECT proowner::regrole::text FROM pg_proc
           WHERE oid = to_regprocedure(tenants_function)) <> directory_role THEN
    EXECUTE 'DROP FUNCTION ' || tenants_function;
  END IF;
  EXECUTE format('GRANT CREATE ON SCHEMA identity TO %I', directory_role);
  EXECUTE format('SET LOCAL ROLE %I', directory_role);
  IF have_requests THEN
    EXECUTE $function$
      CREATE OR REPLACE FUNCTION identity.data_requests_open()
      RETURNS TABLE (kind text, open bigint, overdue bigint)
      LANGUAGE sql STABLE SECURITY DEFINER
      SET search_path = pg_catalog, pg_temp
      AS $body$
        SELECT r.kind::text,
               count(*),
               count(*) FILTER (
                 WHERE r.deadline_at < now()
                   AND (r.status = 'received' OR r.kind = 'deletion')
               )
          FROM identity.data_request AS r
         WHERE r.status <> 'completed'
           AND NOT (r.kind = 'export' AND r.status = 'in_progress' AND r.deadline_at < now())
         GROUP BY r.kind
      $body$
    $function$;
    EXECUTE 'REVOKE ALL ON FUNCTION ' || requests_function || ' FROM PUBLIC';
    FOREACH caller IN ARRAY callers LOOP
      IF EXISTS (SELECT FROM pg_roles WHERE rolname = caller) THEN
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO %I', requests_function, caller);
      END IF;
    END LOOP;
  END IF;
  IF have_tenants THEN
    -- q is matched literally (its LIKE wildcards escaped); the newest subscription by when it
    -- started gives the plan key and status, whatever that status is (what the plan entitles
    -- the tenant to is GET /v1/identity/entitlements); a cursor naming no tenant reads nothing.
    EXECUTE $function$
      CREATE OR REPLACE FUNCTION identity.tenant_directory(
        q text, after uuid, lim integer, only_id uuid DEFAULT NULL
      )
      RETURNS TABLE (
        id uuid, kind text, name text, status text, created_at timestamptz,
        plan_key text, subscription_status text, users bigint, active_users bigint
      )
      LANGUAGE sql STABLE SECURITY DEFINER
      SET search_path = pg_catalog, pg_temp
      AS $body$
        WITH start AS (
          SELECT t.name, t.id FROM identity.tenant AS t WHERE t.id = after
        ),
        pattern AS (
          SELECT '%' || replace(replace(replace(q, '\', '\\'), '%', '\%'), '_', '\_') || '%'
                 AS like_text
        )
        SELECT t.id,
               t.kind::text,
               t.name::text,
               t.status::text,
               t.created_at,
               coalesce(s.plan_key::text, ''),
               coalesce(s.status::text, ''),
               (SELECT count(*) FROM identity.app_user AS u WHERE u.tenant_id = t.id),
               (SELECT count(*) FROM identity.app_user AS u
                 WHERE u.tenant_id = t.id AND u.status = 'active')
          FROM identity.tenant AS t
          LEFT JOIN LATERAL (
            SELECT b.plan_key, b.status
              FROM identity.billing_subscription AS b
             WHERE b.tenant_id = t.id
             ORDER BY b.started_at DESC, b.provider_subscription_id DESC
             LIMIT 1
          ) AS s ON true
         WHERE (only_id IS NULL OR t.id = only_id)
           AND (q IS NULL OR q = ''
                OR t.name ILIKE (SELECT like_text FROM pattern)
                OR t.id::text = lower(q))
           AND (after IS NULL OR (t.name, t.id) > (SELECT start.name, start.id FROM start))
         ORDER BY t.name, t.id
         LIMIT coalesce(lim, 50)
      $body$
    $function$;
    EXECUTE 'REVOKE ALL ON FUNCTION ' || tenants_function || ' FROM PUBLIC';
    FOREACH caller IN ARRAY callers LOOP
      IF EXISTS (SELECT FROM pg_roles WHERE rolname = caller) THEN
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO %I', tenants_function, caller);
      END IF;
    END LOOP;
  END IF;
  EXECUTE format('SET LOCAL ROLE %I', owner_name);
  EXECUTE format('REVOKE CREATE ON SCHEMA identity FROM %I', directory_role);
END
$directory$;

-- The profile directory: the same pattern for the profile schema. The NOLOGIN role
-- cw_profile_directory owns two SECURITY DEFINER functions that read across tenants and answer
-- no row of a profile:
--   - profile.attribute_usage(): how many profile nodes hold each attribute in each state
--     (key, state, count: distinct nodes, a per-year value counting its node once), for the
--     regulatory team's ontology browser (GET /v1/profile/admin/attribute-usage); never a value.
--   - profile.tenant_directory(): the ids of the tenants that have profile nodes, which the
--     worker's financial year schedule (flag profile.fy_schedule) visits one tenant unit of work
--     at a time; it needs no service token and no row-level security bypass.
-- Only cw_profile and cw_app may EXECUTE them; PUBLIC may not. The role holds USAGE on profile,
-- SELECT on the columns of profile_attribute and profile_node the functions read, and one read
-- policy per table (<table>_directory), and nothing else; nobody logs in as it. The owner's
-- membership, the grants as the function's owner and the CREATE on the schema while the
-- functions are made follow the identity directory above. Until profile's migration 0001 has
-- made the tables, the role is created and the rest skipped with a notice.
DO $profile_directory$
DECLARE
  directory_role CONSTANT text := 'cw_profile_directory';
  callers CONSTANT text[] := ARRAY['cw_profile', 'cw_app'];
  owner_name CONSTANT text := current_user;
  functions CONSTANT text[] := ARRAY['profile.attribute_usage()', 'profile.tenant_directory()'];
  found_role record;
  caller text;
  function_name text;
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

  IF to_regclass('profile.profile_attribute') IS NULL
     OR to_regclass('profile.profile_node') IS NULL THEN
    RAISE NOTICE 'profile''s tables do not exist yet: % gets its functions once this file runs '
      'after profile''s migrations', directory_role;
    RETURN;
  END IF;

  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = owner_name)
     AND NOT pg_has_role(owner_name, directory_role, 'SET') THEN
    EXECUTE format('GRANT %I TO %I WITH INHERIT FALSE, SET TRUE', directory_role, owner_name);
  END IF;
  EXECUTE format('GRANT USAGE ON SCHEMA profile TO %I', directory_role);
  EXECUTE format(
    'GRANT SELECT (node_id, key, state) ON profile.profile_attribute TO %I', directory_role
  );
  EXECUTE format('GRANT SELECT (tenant_id) ON profile.profile_node TO %I', directory_role);
  IF NOT EXISTS (
    SELECT FROM pg_policies
     WHERE schemaname = 'profile' AND tablename = 'profile_attribute'
       AND policyname = 'profile_attribute_directory'
  ) THEN
    EXECUTE format(
      'CREATE POLICY profile_attribute_directory ON profile.profile_attribute FOR SELECT TO %I '
      'USING (true)',
      directory_role
    );
  END IF;
  IF NOT EXISTS (
    SELECT FROM pg_policies
     WHERE schemaname = 'profile' AND tablename = 'profile_node'
       AND policyname = 'profile_node_directory'
  ) THEN
    EXECUTE format(
      'CREATE POLICY profile_node_directory ON profile.profile_node FOR SELECT TO %I '
      'USING (true)',
      directory_role
    );
  END IF;

  FOREACH function_name IN ARRAY functions LOOP
    IF to_regprocedure(function_name) IS NOT NULL
       AND (SELECT proowner::regrole::text FROM pg_proc
             WHERE oid = to_regprocedure(function_name)) <> directory_role THEN
      EXECUTE 'DROP FUNCTION ' || function_name;
    END IF;
  END LOOP;
  EXECUTE format('GRANT CREATE ON SCHEMA profile TO %I', directory_role);
  EXECUTE format('SET LOCAL ROLE %I', directory_role);
  EXECUTE $function$
    CREATE OR REPLACE FUNCTION profile.attribute_usage()
    RETURNS TABLE (key text, state text, count bigint)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $body$
      SELECT a.key::text, a.state::text, count(DISTINCT a.node_id)
        FROM profile.profile_attribute AS a
       GROUP BY a.key, a.state
       ORDER BY a.key, a.state
    $body$
  $function$;
  EXECUTE $function$
    CREATE OR REPLACE FUNCTION profile.tenant_directory()
    RETURNS TABLE (tenant_id uuid)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $body$
      SELECT DISTINCT n.tenant_id
        FROM profile.profile_node AS n
       ORDER BY n.tenant_id
    $body$
  $function$;
  FOREACH function_name IN ARRAY functions LOOP
    EXECUTE 'REVOKE ALL ON FUNCTION ' || function_name || ' FROM PUBLIC';
    FOREACH caller IN ARRAY callers LOOP
      IF EXISTS (SELECT FROM pg_roles WHERE rolname = caller) THEN
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO %I', function_name, caller);
      END IF;
    END LOOP;
  END LOOP;
  EXECUTE format('SET LOCAL ROLE %I', owner_name);
  EXECUTE format('REVOKE CREATE ON SCHEMA profile FROM %I', directory_role);
END
$profile_directory$;
