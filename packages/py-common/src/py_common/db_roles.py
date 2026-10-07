"""The services' database roles, and how a test database gets them.

``infra/dev/postgres/roles.sql`` gives each service schema a login role, ``cw_<schema>``, that is
neither a superuser nor bypasses row-level security: it uses its own schema and ``public``, reads
and writes the tables of its schema except ``alembic_version``, and may only add rows to the audit
log (``cw_identity`` also reads them). ``dev-passwords.sql`` beside it gives each role its own name
as a password, a placeholder for the dev stack (``make db-roles``); a deployment sets the
passwords from its secret store.

- ``SERVICE_SCHEMAS``: the schemas with a role, in the order roles.sql lists them.
- ``role_name(schema)`` and ``dev_password(schema)``: ``cw_<schema>``, twice.
- ``roles_sql()`` and ``dev_passwords_sql()``: the two files, read from the checkout this package
  sits in (an integration test's, never an image's).
- ``apply_roles(url)``: both files, run as the URL's user, which must own the schemas (a test
  container's user). Run it after the migrations and after any audit table a test installs: a
  schema that does not exist yet gets nothing, as on the dev stack.
- ``as_role(url, schema)``: the URL with the schema's role and its dev password in place of its
  user; the rest of it, the ``search_path`` option included, stays as it is.
"""

from functools import cache
from pathlib import Path
from typing import Final

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

SERVICE_SCHEMAS: Final = (
    "identity",
    "profile",
    "rulebook",
    "applicability",
    "obligation",
    "notification",
    "qa",
    "llm_gateway",
    "eval",
    "pipeline",
)
ROLE_PREFIX: Final = "cw_"
AUDIT_READER: Final = "cw_identity"
"""The one role that reads the audit log, for the audit trail route."""
SQL_DIR: Final = Path("infra", "dev", "postgres")
ROLES_FILE: Final = "roles.sql"
DEV_PASSWORDS_FILE: Final = "dev-passwords.sql"


def role_name(schema: str) -> str:
    """``cw_<schema>``, the role of a service schema."""
    if schema not in SERVICE_SCHEMAS:
        raise ValueError(f"{schema!r} is not a service schema; the schemas are {SERVICE_SCHEMAS}")
    return ROLE_PREFIX + schema


def dev_password(schema: str) -> str:
    """The role's password on the dev stack and in tests: its own name, a placeholder."""
    return role_name(schema)


@cache
def sql_dir() -> Path:
    """``infra/dev/postgres`` of the checkout this file sits in."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / SQL_DIR
        if (candidate / ROLES_FILE).is_file():
            return candidate
    raise FileNotFoundError(
        f"no {SQL_DIR / ROLES_FILE} above {Path(__file__).resolve()}: the role files are read "
        "from a checkout of the repository"
    )


def roles_sql() -> str:
    return (sql_dir() / ROLES_FILE).read_text(encoding="utf-8")


def dev_passwords_sql() -> str:
    return (sql_dir() / DEV_PASSWORDS_FILE).read_text(encoding="utf-8")


def apply_roles(url: str) -> None:
    """Run roles.sql, then dev-passwords.sql, as the URL's user in one transaction; safe to
    repeat, as the files are."""
    engine = create_engine(url, poolclass=NullPool)
    try:
        connection = engine.raw_connection()
        try:
            cursor = connection.cursor()
            # No parameters: the driver sends each file as it is, several statements in one go,
            # and reads no placeholder into format()'s %I and %L.
            cursor.execute(roles_sql())
            cursor.execute(dev_passwords_sql())
            cursor.close()
            connection.commit()
        finally:
            connection.close()
    finally:
        engine.dispose()


def as_role(url: str, schema: str) -> str:
    """``url`` connecting as the schema's role with its dev password."""
    role = make_url(url).set(username=role_name(schema), password=dev_password(schema))
    return role.render_as_string(hide_password=False)


__all__ = [
    "AUDIT_READER",
    "SERVICE_SCHEMAS",
    "apply_roles",
    "as_role",
    "dev_password",
    "dev_passwords_sql",
    "role_name",
    "roles_sql",
]
