"""``cw-mvp migrate``: every service schema's migrations, as the role that owns the schemas.

For each registered service in the registry's order (identity first: its migration creates
``audit.event``, which every service writes), or for the one ``--service`` names, it:

1. creates the service's schema when the database lacks it, as a managed database does at
   first (``infra/dev/postgres/init.sql`` makes them on the dev stack);
2. runs ``alembic upgrade head`` with the service's ``alembic.ini`` in a child process, the way
   ``make migrate`` does: ``CW_DATABASE_URL`` is the owner's URL with the schema first on its
   ``search_path``, and ``CW_DB_SCHEMA`` the schema that holds the service's ``alembic_version``;
3. reports the revision it found and the one it left.

The owner's URL is ``CW_MIGRATION_DATABASE_URL`` (``ReleaseSettings``); the app's runtime URL,
``CW_DATABASE_URL``, never migrates. Outside local and test the two must connect as different
roles: the app's role owns nothing and row-level security applies to it
(``infra/dev/postgres/50-app-role.sql``), while migrations need the owner. A failed migration
stops the run with the end of alembic's output, and the services after it are not migrated.

The alembic files are found beside each service's sources (``services/<name>/alembic.ini``),
where a checkout and the image keep them. Running it again changes nothing.
"""

import inspect
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Protocol, Self

from sqlalchemy import Column, MetaData, String, Table, create_engine, select
from sqlalchemy import inspect as inspect_database
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema

from cw_mvp.registry import REGISTRY, ServiceEntry
from cw_mvp.settings import ReleaseSettings
from py_common.settings import SCHEMA_NAME, with_search_path

LOCAL_ENVIRONMENTS: Final = frozenset({"local", "test"})
"""Where the app's runtime URL may also be the owner's (a dev database has one superuser)."""
ALEMBIC_INI: Final = "alembic.ini"
VERSION_TABLE: Final = "alembic_version"
POSTGRES_PORT: Final = 5432
OUTPUT_LINES: Final = 20
"""How many of alembic's last output lines a failure shows."""


class MigrationRefusedError(RuntimeError):
    """The settings do not allow migrating; the message says why and names no secret."""


class MigrationFailedError(RuntimeError):
    """alembic failed for one service; the message carries the end of its output."""


@dataclass(frozen=True, slots=True)
class MigrationStep:
    service: str
    schema: str
    alembic_ini: Path


@dataclass(frozen=True, slots=True)
class MigrationResult:
    step: MigrationStep
    before: str | None
    after: str | None
    schema_created: bool

    @property
    def ran(self) -> bool:
        return self.before != self.after

    def line(self) -> str:
        """What happened, as ``migrate`` reports it."""
        step = self.step
        if self.ran:
            outcome = f"{self.before or 'base'} -> {self.after}"
        elif self.after is None:
            outcome = "no migrations"
        else:
            outcome = f"at {self.after}, nothing to run"
        created = ", schema created" if self.schema_created else ""
        return f"  {step.service:<22} schema {step.schema:<14} {outcome}{created}"


class Catalog(Protocol):
    """The database as the migration sees it, connected as the owner."""

    def has_schema(self, schema: str) -> bool: ...

    def create_schema(self, schema: str) -> None: ...

    def revision(self, schema: str) -> str | None: ...

    def close(self) -> None: ...


Runner = Callable[[MigrationStep, str], None]
"""Runs one step's ``alembic upgrade head`` on the owner's URL; raises MigrationFailedError."""


class PostgresCatalog:
    """The owner's connection: one engine without a pool, a connection per question."""

    def __init__(self, url: str) -> None:
        self._engine = create_engine(url, poolclass=NullPool)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.close()

    def has_schema(self, schema: str) -> bool:
        with self._engine.connect() as connection:
            return inspect_database(connection).has_schema(_schema(schema))

    def create_schema(self, schema: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(CreateSchema(_schema(schema), if_not_exists=True))

    def revision(self, schema: str) -> str | None:
        """The revision in the schema's ``alembic_version``; None before the first migration."""
        name = _schema(schema)
        with self._engine.connect() as connection:
            if not inspect_database(connection).has_table(VERSION_TABLE, schema=name):
                return None
            table = Table(VERSION_TABLE, MetaData(), Column("version_num", String), schema=name)
            value = connection.execute(select(table.c.version_num)).scalar()
        return None if value is None else str(value)

    def close(self) -> None:
        self._engine.dispose()


def _schema(schema: str) -> str:
    if not SCHEMA_NAME.fullmatch(schema):
        raise ValueError(f"schema must be a lower-case Postgres identifier, got {schema!r}")
    return schema


def alembic_ini(entry: ServiceEntry[Any]) -> Path:
    """``services/<name>/alembic.ini``: beside the sources ``<pkg>.main`` is loaded from."""
    return Path(inspect.getfile(entry.build)).resolve().parents[2] / ALEMBIC_INI


def steps(
    services: Sequence[str] = (), registry: Sequence[ServiceEntry[Any]] = REGISTRY
) -> tuple[MigrationStep, ...]:
    """The registry's services in order, or the ones ``services`` names."""
    known = {entry.name for entry in registry}
    unknown = sorted(set(services) - known)
    if unknown:
        raise MigrationRefusedError(f"no service named {unknown}; the services are {sorted(known)}")
    return tuple(
        MigrationStep(entry.name, entry.schema, alembic_ini(entry))
        for entry in registry
        if not services or entry.name in services
    )


def where(url: str) -> str:
    """Who and what a URL connects to, without its password: ``cw on compliancewatch at
    postgres:5432``."""
    parsed = _parsed(url, "the database URL")
    return f"{parsed.username} on {parsed.database} at {parsed.host}:{parsed.port or POSTGRES_PORT}"


def _parsed(url: str, name: str) -> URL:
    try:
        return make_url(url)
    except ArgumentError:
        raise MigrationRefusedError(f"{name} is not a database URL") from None


def _identity(url: URL) -> tuple[str | None, str, int, str | None]:
    return (url.username, (url.host or "").lower(), url.port or POSTGRES_PORT, url.database)


def owner_url(settings: ReleaseSettings) -> str:
    """``CW_MIGRATION_DATABASE_URL``, after the checks: it is set, and outside local and test it
    does not connect as the app's runtime role to the same database."""
    secret = settings.migration_database_url
    url = "" if secret is None else secret.get_secret_value().strip()
    if not url:
        raise MigrationRefusedError(
            "CW_MIGRATION_DATABASE_URL is not set: migrations run as the role that owns the "
            "service schemas, never over the app's runtime URL (CW_DATABASE_URL)"
        )
    owner = _parsed(url, "CW_MIGRATION_DATABASE_URL")
    runtime = _parsed(settings.database_url, "CW_DATABASE_URL")
    if settings.env not in LOCAL_ENVIRONMENTS and _identity(owner) == _identity(runtime):
        raise MigrationRefusedError(
            f"CW_MIGRATION_DATABASE_URL and CW_DATABASE_URL both connect as {owner.username} to "
            f"{owner.database} (CW_ENV={settings.env}): the app's runtime role must not be the "
            "one that migrates; give CW_MIGRATION_DATABASE_URL the URL of the schemas' owner"
        )
    return url


def alembic_upgrade(step: MigrationStep, url: str) -> None:
    """``alembic upgrade head`` for one service in a child process, as ``make migrate`` runs it:
    each service's ``migrations/env.py`` configures logging for its own process."""
    environment = {
        **os.environ,
        "CW_DATABASE_URL": with_search_path(url, step.schema),
        "CW_DB_SCHEMA": step.schema,
    }
    command = [sys.executable, "-m", "alembic", "-c", str(step.alembic_ini), "upgrade", "head"]
    finished = subprocess.run(command, env=environment, capture_output=True, text=True, check=False)
    if finished.returncode != 0:
        output = "\n".join((finished.stdout, finished.stderr)).strip().splitlines()
        raise MigrationFailedError(
            f"{step.service}: alembic upgrade head exited with {finished.returncode}:\n"
            + "\n".join(f"    {line}" for line in output[-OUTPUT_LINES:])
        )


def migrate(
    settings: ReleaseSettings,
    *,
    services: Sequence[str] = (),
    catalog_factory: Callable[[str], Catalog] = PostgresCatalog,
    runner: Runner = alembic_upgrade,
    report: Callable[[str], None] = lambda _: None,
) -> list[MigrationResult]:
    """Migrate the chosen services in order; ``report`` gets each one's line as it finishes."""
    url = owner_url(settings)
    chosen = steps(services)
    missing = [str(step.alembic_ini) for step in chosen if not step.alembic_ini.is_file()]
    if missing:
        raise MigrationRefusedError(
            f"no alembic files at {missing}: cw-mvp migrate runs from a checkout or the image, "
            "which keep each service's alembic.ini and migrations beside its sources"
        )
    report(f"migrate: as {where(url)} (CW_MIGRATION_DATABASE_URL)")
    results: list[MigrationResult] = []
    catalog = catalog_factory(url)
    try:
        for step in chosen:
            created = not catalog.has_schema(step.schema)
            if created:
                catalog.create_schema(step.schema)
            before = catalog.revision(step.schema)
            runner(step, url)
            result = MigrationResult(step, before, catalog.revision(step.schema), created)
            report(result.line())
            results.append(result)
    finally:
        catalog.close()
    return results


def summary(results: Sequence[MigrationResult]) -> str:
    ran = sum(result.ran for result in results)
    noun = "service" if len(results) == 1 else "services"
    return f"migrate: {len(results)} {noun}, {ran} migrated, {len(results) - ran} unchanged"
