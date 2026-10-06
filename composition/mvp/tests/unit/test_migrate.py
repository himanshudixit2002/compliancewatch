"""``cw-mvp migrate``: the owner's URL only, every schema in order, and what ran."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from cw_mvp.migrate import (
    MigrationFailedError,
    MigrationRefusedError,
    MigrationStep,
    alembic_ini,
    alembic_upgrade,
    migrate,
    owner_url,
    steps,
    summary,
    where,
)
from cw_mvp.registry import REGISTRY
from cw_mvp.settings import ReleaseSettings

REPO = Path(__file__).resolve().parents[4]
OWNER = "postgresql+psycopg://owner:owner-password@db.internal:5432/compliancewatch"
APP = "postgresql+psycopg://cw_app:app-password@db.internal:5432/compliancewatch"


def settings(**values: Any) -> ReleaseSettings:
    given: dict[str, Any] = {
        "_env_file": None,
        "service_name": "cw-mvp-release",
        "database_url": APP,
        "migration_database_url": SecretStr(OWNER),
    }
    given.update(values)
    return ReleaseSettings(**given)


class FakeCatalog:
    """Schemas and their revisions; the runner moves a schema to its head."""

    def __init__(self, schemas: dict[str, str | None]) -> None:
        self.schemas = dict(schemas)
        self.created: list[str] = []
        self.closed = False

    def has_schema(self, schema: str) -> bool:
        return schema in self.schemas

    def create_schema(self, schema: str) -> None:
        self.created.append(schema)
        self.schemas[schema] = None

    def revision(self, schema: str) -> str | None:
        return self.schemas[schema]

    def close(self) -> None:
        self.closed = True


class FakeRunner:
    def __init__(self, catalog: FakeCatalog, heads: dict[str, str | None]) -> None:
        self.catalog = catalog
        self.heads = heads
        self.ran: list[tuple[str, str]] = []

    def __call__(self, step: MigrationStep, url: str) -> None:
        self.ran.append((step.service, url))
        self.catalog.schemas[step.schema] = self.heads.get(step.service)


HEADS: dict[str, str | None] = {entry.name: "0001" for entry in REGISTRY} | {
    "qa": None,
    "pipeline": None,
}


def run(
    catalog: FakeCatalog, release: ReleaseSettings | None = None, **kwargs: Any
) -> tuple[list[str], FakeRunner, list[Any]]:
    lines: list[str] = []
    runner = FakeRunner(catalog, HEADS)
    results = migrate(
        release or settings(),
        catalog_factory=lambda url: catalog,
        runner=runner,
        report=lines.append,
        **kwargs,
    )
    return lines, runner, results


def test_every_service_has_its_alembic_files_beside_its_sources() -> None:
    for entry in REGISTRY:
        ini = alembic_ini(entry)
        assert ini == REPO / "services" / entry.name / "alembic.ini"
        assert ini.is_file()


def test_the_steps_follow_the_registry_identity_first() -> None:
    chosen = steps()
    assert [step.service for step in chosen] == [entry.name for entry in REGISTRY]
    assert chosen[0].service == "identity"
    assert [step.schema for step in steps(["applicability-engine"])] == ["applicability"]
    with pytest.raises(MigrationRefusedError, match="no service named"):
        steps(["billing"])


def test_a_fresh_database_gets_every_schema_and_its_migrations_as_the_owner() -> None:
    catalog = FakeCatalog({})
    lines, runner, results = run(catalog)
    assert catalog.created == [entry.schema for entry in REGISTRY]
    assert [service for service, _ in runner.ran] == [entry.name for entry in REGISTRY]
    assert {url for _, url in runner.ran} == {OWNER}
    assert catalog.closed
    assert lines[0] == (
        "migrate: as owner on compliancewatch at db.internal:5432 (CW_MIGRATION_DATABASE_URL)"
    )
    assert "owner-password" not in "\n".join(lines)
    assert lines[1].split() == [
        "identity", "schema", "identity", "base", "->", "0001,", "schema", "created",
    ]  # fmt: skip
    assert "no migrations, schema created" in lines[7]
    assert summary(results) == "migrate: 10 services, 8 migrated, 2 unchanged"


def test_a_second_run_runs_alembic_again_and_reports_nothing_migrated() -> None:
    catalog = FakeCatalog({})
    run(catalog)
    lines, runner, results = run(catalog)
    assert len(runner.ran) == len(REGISTRY)
    assert not any(result.ran or result.schema_created for result in results)
    assert "at 0001, nothing to run" in lines[1]
    assert summary(results) == "migrate: 10 services, 0 migrated, 10 unchanged"


def test_one_service_runs_alone() -> None:
    catalog = FakeCatalog({"rulebook": "0006"})
    lines, runner, results = run(catalog, services=["rulebook"])
    assert [service for service, _ in runner.ran] == ["rulebook"]
    assert catalog.created == []
    assert [result.line().split()[-3:] for result in results] == [["0006", "->", "0001"]]
    assert summary(results) == "migrate: 1 service, 1 migrated, 0 unchanged"
    assert len(lines) == 2


def test_a_failed_migration_stops_the_run_and_closes_the_catalog() -> None:
    catalog = FakeCatalog({})
    ran: list[str] = []

    def failing(step: MigrationStep, url: str) -> None:
        ran.append(step.service)
        if step.service == "rulebook":
            raise MigrationFailedError("rulebook: alembic upgrade head exited with 1")

    with pytest.raises(MigrationFailedError, match="rulebook"):
        migrate(settings(), catalog_factory=lambda url: catalog, runner=failing)
    assert ran == ["identity", "profile", "rulebook"]
    assert catalog.closed


def test_without_the_owners_url_nothing_migrates_even_locally() -> None:
    catalog = FakeCatalog({})
    for value in (None, SecretStr(""), SecretStr("  ")):
        with pytest.raises(MigrationRefusedError, match="CW_MIGRATION_DATABASE_URL is not set"):
            run(catalog, settings(migration_database_url=value))
    assert catalog.schemas == {}


@pytest.mark.parametrize("env", ["staging", "prod"])
@pytest.mark.parametrize(
    "runtime",
    [
        OWNER,
        OWNER.replace("owner-password", "other") + "?options=-csearch_path%3Dprofile%2Cpublic",
        "postgresql+psycopg://owner:x@DB.internal/compliancewatch",
    ],
)
def test_outside_local_the_runtime_role_never_migrates(env: str, runtime: str) -> None:
    release = settings(env=env, auth_mode="token", database_url=runtime)
    with pytest.raises(MigrationRefusedError) as refused:
        owner_url(release)
    message = str(refused.value)
    assert "both connect as owner to compliancewatch" in message
    assert "owner-password" not in message


@pytest.mark.parametrize("env", ["local", "test"])
def test_locally_the_owner_may_be_the_runtime_role(env: str) -> None:
    assert owner_url(settings(env=env, database_url=OWNER)) == OWNER


@pytest.mark.parametrize(
    "runtime",
    [APP, OWNER.replace("compliancewatch", "other"), OWNER.replace("db.internal", "replica")],
)
def test_another_role_or_database_is_not_the_owner(runtime: str) -> None:
    release = settings(env="prod", auth_mode="token", database_url=runtime)
    assert owner_url(release) == OWNER


def test_a_url_that_is_not_a_database_url_is_refused_without_its_text() -> None:
    with pytest.raises(MigrationRefusedError) as refused:
        owner_url(settings(migration_database_url=SecretStr("not a url secret")))
    assert str(refused.value) == "CW_MIGRATION_DATABASE_URL is not a database URL"


def test_where_names_the_role_database_and_host_without_the_password() -> None:
    assert where(OWNER) == "owner on compliancewatch at db.internal:5432"
    assert where("postgresql+psycopg://cw@localhost/db") == "cw on db at localhost:5432"


def test_missing_alembic_files_are_refused_before_anything_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("cw_mvp.migrate.alembic_ini", lambda entry: tmp_path / "alembic.ini")
    catalog = FakeCatalog({})
    with pytest.raises(MigrationRefusedError, match="no alembic files"):
        run(catalog)
    assert catalog.created == []


def test_alembic_runs_with_the_schema_first_on_the_owners_search_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class Finished:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command: list[str], **kwargs: Any) -> Finished:
        seen["command"] = command
        seen["env"] = kwargs["env"]
        return Finished()

    monkeypatch.setattr("cw_mvp.migrate.subprocess.run", fake_run)
    step = MigrationStep("rulebook", "rulebook", REPO / "services/rulebook/alembic.ini")
    alembic_upgrade(step, OWNER)
    assert seen["command"][1:] == [
        "-m", "alembic", "-c", str(step.alembic_ini), "upgrade", "head",
    ]  # fmt: skip
    assert seen["env"]["CW_DATABASE_URL"] == OWNER + "?options=-csearch_path%3Drulebook%2Cpublic"
    assert seen["env"]["CW_DB_SCHEMA"] == "rulebook"


def test_a_failing_alembic_reports_the_end_of_its_output(monkeypatch: pytest.MonkeyPatch) -> None:
    class Finished:
        returncode = 1
        stdout = "\n".join(f"line {n}" for n in range(40))
        stderr = "sqlalchemy.exc.ProgrammingError: permission denied for schema rulebook"

    monkeypatch.setattr("cw_mvp.migrate.subprocess.run", lambda *args, **kwargs: Finished())
    step = MigrationStep("rulebook", "rulebook", REPO / "services/rulebook/alembic.ini")
    with pytest.raises(MigrationFailedError) as failed:
        alembic_upgrade(step, OWNER)
    message = str(failed.value)
    assert message.startswith("rulebook: alembic upgrade head exited with 1")
    assert "permission denied for schema rulebook" in message
    assert "line 21" in message
    assert "line 20\n" not in message
