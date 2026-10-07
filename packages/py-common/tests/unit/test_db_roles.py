"""The service roles' names, their dev passwords and the two SQL files agree, and a URL can be
turned into one of the roles'."""

import re

import pytest
from sqlalchemy.engine import make_url

from py_common.db_roles import (
    AUDIT_READER,
    SERVICE_SCHEMAS,
    as_role,
    dev_password,
    dev_passwords_sql,
    role_name,
    roles_sql,
)

OWNER = "postgresql+psycopg://cw:cw@localhost:5432/compliancewatch"


def test_each_schema_has_a_role_whose_dev_password_is_its_name() -> None:
    assert len(set(SERVICE_SCHEMAS)) == 10
    for schema in SERVICE_SCHEMAS:
        assert role_name(schema) == f"cw_{schema}"
        assert dev_password(schema) == role_name(schema)
    assert role_name("identity") == AUDIT_READER


@pytest.mark.parametrize("schema", ["audit", "public", "cw", "Identity", ""])
def test_a_schema_without_a_role_is_refused(schema: str) -> None:
    with pytest.raises(ValueError, match="is not a service schema"):
        role_name(schema)


def test_roles_sql_lists_the_same_schemas_and_reads_the_audit_log_as_identity_only() -> None:
    text = roles_sql()
    listed = re.search(r"service_schemas CONSTANT text\[\] := ARRAY\[(.*?)\];", text, re.S)
    assert listed is not None
    assert tuple(re.findall(r"'([a-z_]+)'", listed.group(1))) == SERVICE_SCHEMAS
    assert f"audit_reader CONSTANT text := '{AUDIT_READER}';" in text
    assert "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT" in text
    assert "PASSWORD '" not in text, "a password belongs in dev-passwords.sql or the secret store"


def test_dev_passwords_sql_sets_each_role_s_name_as_its_password_and_nothing_else() -> None:
    statements = [
        line for line in dev_passwords_sql().splitlines() if line and not line.startswith("--")
    ]
    assert statements == [
        f"ALTER ROLE {role_name(schema)} PASSWORD '{dev_password(schema)}';"
        for schema in SERVICE_SCHEMAS
    ]


def test_both_files_are_plain_sql_any_client_runs() -> None:
    """No psql meta-command: the postgres image, make db-roles (psql) and the integration tests
    (one driver call) all run them as they are."""
    for text in (roles_sql(), dev_passwords_sql()):
        assert not [line for line in text.splitlines() if line.lstrip().startswith("\\")]
        assert ":'" not in text, "a psql variable would not be set outside make"


def test_as_role_swaps_the_user_and_keeps_the_rest_of_the_url() -> None:
    url = OWNER + "?options=-csearch_path%3Dobligation%2Cpublic"
    role = make_url(as_role(url, "obligation"))
    assert (role.username, role.password) == ("cw_obligation", "cw_obligation")
    assert (role.host, role.port, role.database) == ("localhost", 5432, "compliancewatch")
    assert role.query == {"options": "-csearch_path=obligation,public"}
    assert role.drivername == "postgresql+psycopg"
    with pytest.raises(ValueError, match="is not a service schema"):
        as_role(url, "audit")
