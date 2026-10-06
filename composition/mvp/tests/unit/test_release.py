"""``cw-mvp release``: migrate, then the topics, and nothing else; the commands that route to it."""

from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import pytest
from pydantic import SecretStr

from cw_mvp import release as release_module
from cw_mvp.cli import main
from cw_mvp.migrate import MigrationFailedError, MigrationResult, MigrationStep
from cw_mvp.settings import ReleaseSettings
from cw_mvp.topics import TOPICS_FILE, BrokerTopic, TopicSpec, load
from py_common.kafka import KafkaClientConfig

OWNER = "postgresql+psycopg://owner:owner-password@localhost:5432/compliancewatch"


def settings(**values: Any) -> ReleaseSettings:
    given: dict[str, Any] = {
        "_env_file": None,
        "service_name": "cw-mvp-release",
        "migration_database_url": SecretStr(OWNER),
        "kafka_bootstrap": "broker.invalid:9092",
    }
    given.update(values)
    return ReleaseSettings(**given)


class Broker:
    """Every topic the file lists but one, on one broker; or one that cannot be reached."""

    def __init__(self, *, reachable: bool = True) -> None:
        self.reachable = reachable
        self.created: list[str] = []
        self.held = {
            spec.name: BrokerTopic(spec.name, spec.partitions, spec.configs())
            for spec in load().topics[1:]
        }

    def __call__(self, config: KafkaClientConfig) -> "Broker":
        self.config = config
        return self

    async def __aenter__(self) -> Self:
        if not self.reachable:
            raise ConnectionError("Unable to bootstrap from [('broker.invalid', 9092)]")
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        return None

    async def brokers(self) -> int:
        return 1

    async def topics(self, with_configs: Collection[str]) -> Mapping[str, BrokerTopic]:
        return dict(self.held)

    async def create(self, topics: Sequence[TopicSpec], replication_factor: int) -> None:
        self.created += [spec.name for spec in topics]


def migrated(monkeypatch: pytest.MonkeyPatch, *, fail: bool = False) -> list[Sequence[str]]:
    """Replace the migration with one that reports a migrated identity, or fails."""
    calls: list[Sequence[str]] = []

    def fake(settings: ReleaseSettings, *, services: Sequence[str] = (), **_: Any) -> list[Any]:
        calls.append(services)
        if fail:
            raise MigrationFailedError("rulebook: alembic upgrade head exited with 1")
        step = MigrationStep("identity", "identity", Path("services/identity/alembic.ini"))
        return [MigrationResult(step, None, "0005", schema_created=True)]

    monkeypatch.setattr(release_module, "migrate", fake)
    return calls


def test_release_migrates_then_creates_the_missing_topics(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = migrated(monkeypatch)
    broker = Broker()
    status = release_module.run_release(settings(worker_kafka_enabled=True), admin_factory=broker)
    assert status == 0
    assert calls == [()]
    assert broker.created == [load().topics[0].name]
    assert broker.config.bootstrap_servers == "broker.invalid:9092"
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "release: migrate"
    assert out[1] == "migrate: 1 service, 1 migrated, 0 unchanged"
    assert out[2] == "release: topics apply"
    assert out[3].startswith(f"topics apply: {len(load().topics)} topics in topics.toml, broker ")
    assert out[-2].startswith("topics apply: 1 created, ")
    assert out[-1] == "release: done"


def test_without_kafka_the_release_migrates_and_skips_the_topics(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    migrated(monkeypatch)
    broker = Broker(reachable=False)
    assert release_module.run_release(settings(), admin_factory=broker) == 0
    assert capsys.readouterr().out.splitlines()[-1] == (
        "release: topics skipped, CW_WORKER_KAFKA_ENABLED is off: nothing reads or writes them"
    )


def test_a_failed_migration_stops_the_release_before_the_topics(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    migrated(monkeypatch, fail=True)
    broker = Broker()
    status = release_module.run_release(settings(worker_kafka_enabled=True), admin_factory=broker)
    assert status == 1
    assert broker.created == []
    captured = capsys.readouterr()
    assert "topics" not in captured.out
    assert captured.err == "migrate: rulebook: alembic upgrade head exited with 1\n"


def test_an_unreachable_broker_fails_the_topics_with_its_address(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = release_module.run_topics(settings(), "plan", admin_factory=Broker(reachable=False))
    assert status == 1
    assert capsys.readouterr().err == (
        "topics plan: broker.invalid:9092: ConnectionError: Unable to bootstrap from "
        "[('broker.invalid', 9092)]\n"
    )


def test_the_plan_creates_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    broker = Broker()
    assert release_module.run_topics(settings(), "plan", admin_factory=broker) == 0
    assert broker.created == []
    out = capsys.readouterr().out.splitlines()
    assert out[1].startswith(f"  to create: {load().topics[0].name} (")
    assert out[-1].startswith("topics plan: 1 to create, 0 differ, ")


def test_a_malformed_topics_file_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "topics.toml"
    path.write_text("replication_factor = 0\n", encoding="utf-8")
    status = release_module.run_topics(settings(), "apply", path=path, admin_factory=Broker())
    assert status == 1
    assert "replication_factor must be a whole number" in capsys.readouterr().err


def test_settings_a_class_refuses_are_reported_before_anything_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CW_MVP_PUBLIC_PORT", "8080")
    monkeypatch.setenv("CW_MVP_INTERNAL_PORT", "8080")
    assert main(["release"]) == 1
    err = capsys.readouterr().err.splitlines()
    assert err[0].startswith("refused: the settings are not valid")
    assert err[1].startswith("  shared: CW_MVP_PUBLIC_PORT and CW_MVP_INTERNAL_PORT must differ")


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["migrate"], ("migrate", ())),
        (["migrate", "--service", "rulebook"], ("migrate", ("rulebook",))),
        (["topics", "plan"], ("topics", "plan")),
        (["topics", "apply"], ("topics", "apply")),
        (["release"], ("release", None)),
    ],
)
def test_the_command_line_routes_the_release_commands(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], expected: tuple[str, object]
) -> None:
    seen: list[tuple[str, object]] = []

    def run_migrate(settings: ReleaseSettings, services: Sequence[str] = ()) -> int:
        seen.append(("migrate", tuple(services)))
        return 0

    def run_topics(settings: ReleaseSettings, command: str, path: Path = TOPICS_FILE) -> int:
        seen.append(("topics", command))
        return 0

    def run_release(settings: ReleaseSettings) -> int:
        seen.append(("release", None))
        return 0

    monkeypatch.setattr(release_module, "release_settings", lambda: settings())
    monkeypatch.setattr(release_module, "run_migrate", run_migrate)
    monkeypatch.setattr(release_module, "run_topics", run_topics)
    monkeypatch.setattr(release_module, "run_release", run_release)
    assert main(argv) == 0
    assert seen == [expected]


def test_an_unknown_service_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["migrate", "--service", "billing"])
    assert stopped.value.code == 2


def test_the_commands_stop_when_the_settings_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(release_module, "release_settings", lambda: None)
    for argv in (["migrate"], ["topics", "plan"], ["release"]):
        assert main(argv) == 1
