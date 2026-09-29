"""Cases for the rules in cw.yml, checked by `semgrep --test .semgrep`.

Not imported or run: ruff and pytest skip this directory, and the scan itself ignores it.
"""

import hmac

import httpx
import yaml
from sqlalchemy import text
from sqlalchemy.engine import Connection

EXPECTED = "expected-value-for-the-cases"


def sql_cases(connection: Connection, schema: str, tenant: str) -> None:
    # ruleid: cw-sql-built-by-string-formatting
    connection.execute(text(f"SELECT * FROM {schema}.obligation WHERE tenant_id = '{tenant}'"))
    # ruleid: cw-sql-built-by-string-formatting
    connection.exec_driver_sql(f"SET search_path TO {schema}")
    # ruleid: cw-sql-built-by-string-formatting
    connection.execute(text("SELECT * FROM {}.obligation".format(schema)))
    # ruleid: cw-sql-built-by-string-formatting
    connection.execute(text("SELECT * FROM %s.obligation" % schema))
    query = f"DELETE FROM {schema}.obligation"
    # ruleid: cw-sql-built-by-string-formatting
    connection.execute(text(query))
    # ok: cw-sql-built-by-string-formatting
    connection.execute(text("SELECT set_config(:name, :value, true)"), {"name": "app.tenant_id"})
    # ok: cw-sql-built-by-string-formatting
    connection.execute(text("SELECT 1"))


def comparison_cases(given_token: str, request_signature: str, digest: str, content: str) -> None:
    # ruleid: cw-secret-compared-with-equality
    if given_token == EXPECTED:
        pass
    # ruleid: cw-secret-compared-with-equality
    if EXPECTED != request_signature:
        pass
    # ok: cw-secret-compared-with-equality
    if hmac.compare_digest(given_token.encode(), EXPECTED.encode()):
        pass
    # ok: cw-secret-compared-with-equality
    if given_token == "":
        pass
    # ok: cw-secret-compared-with-equality
    if request_signature is None or len(request_signature) == 0:
        pass
    # ok: cw-secret-compared-with-equality
    if digest != content:
        pass


def tls_cases(url: str) -> None:
    # ruleid: cw-tls-verification-disabled
    httpx.get(url, verify=False)
    # ruleid: cw-tls-verification-disabled
    httpx.Client(timeout=5.0, verify=False)
    # ok: cw-tls-verification-disabled
    httpx.get(url)
    # ok: cw-tls-verification-disabled
    httpx.Client(verify="/etc/ssl/certs/ca-certificates.crt")


def yaml_cases(document: str) -> None:
    # ruleid: cw-yaml-load-without-safe-loader
    yaml.load(document)
    # ruleid: cw-yaml-load-without-safe-loader
    yaml.load(document, Loader=yaml.Loader)
    # ruleid: cw-yaml-load-without-safe-loader
    yaml.unsafe_load(document)
    # ruleid: cw-yaml-load-without-safe-loader
    yaml.full_load(document)
    # ok: cw-yaml-load-without-safe-loader
    yaml.load(document, Loader=yaml.SafeLoader)
    # ok: cw-yaml-load-without-safe-loader
    yaml.safe_load(document)
