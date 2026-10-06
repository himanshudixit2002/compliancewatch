"""``cw-mvp release`` against a real Postgres and Redpanda. Needs Docker.

The database starts empty, as a managed one does: no service schema and no extension. The
release creates every schema, runs every service's migrations to its head as the owner, and
creates every topic of ``topics.toml``; a second release changes nothing. The topics commands
leave a topic the file does not list, and one that differs from it, as they find them.
"""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from testcontainers.community.kafka import RedpandaContainer
from testcontainers.community.postgres import PostgresContainer

from cw_mvp.migrate import PostgresCatalog, alembic_ini
from cw_mvp.registry import REGISTRY
from cw_mvp.release import run_release, run_topics
from cw_mvp.settings import ReleaseSettings
from cw_mvp.topics import BrokerTopic, KafkaTopicAdmin, TopicSpec, load
from py_common.kafka import KafkaClientConfig

pytestmark = pytest.mark.integration

POSTGRES_IMAGE = "pgvector/pgvector:0.8.6-pg16"
REDPANDA_IMAGE = "docker.redpanda.com/redpandadata/redpanda:v26.2.3"
RUNTIME = "postgresql+psycopg://cw_app:cw_app@localhost:5432/compliancewatch"


@pytest.fixture(scope="module")
def owner_url() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        yield container.get_connection_url()


@pytest.fixture(scope="module")
def bootstrap() -> Iterator[str]:
    container = RedpandaContainer(image=REDPANDA_IMAGE)
    container.start(timeout=60)
    try:
        yield container.get_bootstrap_server()
    finally:
        container.stop()


def release_settings(owner_url: str, bootstrap: str) -> ReleaseSettings:
    return ReleaseSettings(
        _env_file=None,
        service_name="cw-mvp-release",
        env="test",
        log_level="WARNING",
        database_url=RUNTIME,
        migration_database_url=SecretStr(owner_url),
        kafka_bootstrap=bootstrap,
        worker_kafka_enabled=True,
    )


def heads() -> dict[str, str | None]:
    """Each service's head revision, from its migration scripts."""
    found: dict[str, str | None] = {}
    for entry in REGISTRY:
        script = ScriptDirectory.from_config(Config(str(alembic_ini(entry))))
        found[entry.schema] = script.get_current_head()
    return found


def broker_topics(bootstrap: str) -> dict[str, BrokerTopic]:
    async def read() -> dict[str, BrokerTopic]:
        async with KafkaTopicAdmin(KafkaClientConfig.of(bootstrap)) as admin:
            return dict(await admin.topics(with_configs=load().names))

    return asyncio.run(read())


def test_a_release_makes_a_fresh_database_and_broker_whole_and_a_second_changes_nothing(
    owner_url: str, bootstrap: str, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = release_settings(owner_url, bootstrap)
    assert run_release(settings) == 0
    first = capsys.readouterr().out
    assert f"migrate: {len(REGISTRY)} services, 9 migrated, 1 unchanged" in first
    assert first.count("schema created") == len(REGISTRY)
    assert f"{len(load().topics)} created, 0 differing, 0 as the file says" in first
    assert first.rstrip().endswith("release: done")

    with PostgresCatalog(owner_url) as catalog:
        revisions = {entry.schema: catalog.revision(entry.schema) for entry in REGISTRY}
        assert catalog.has_schema("audit")
    assert revisions == heads()
    assert revisions["qa"] is None, "qa has no migration"
    assert revisions["identity"] is not None
    assert revisions["pipeline"] == "0003"
    assert revisions["rulebook"] == "0008"

    topics = broker_topics(bootstrap)
    for spec in load().topics:
        assert topics[spec.name].partitions == spec.partitions, spec.name
        assert dict(topics[spec.name].configs) == spec.configs(), spec.name

    assert run_release(settings) == 0
    second = capsys.readouterr().out
    assert f"migrate: {len(REGISTRY)} services, 0 migrated, {len(REGISTRY)} unchanged" in second
    assert "schema created" not in second
    assert f"0 created, 0 differing, {len(load().topics)} as the file says" in second


def test_the_topics_leave_unlisted_and_differing_topics_as_they_are(
    owner_url: str, bootstrap: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    async def make(*specs: TopicSpec) -> None:
        async with KafkaTopicAdmin(KafkaClientConfig.of(bootstrap)) as admin:
            await admin.create(specs, replication_factor=1)

    asyncio.run(
        make(TopicSpec("drift.listed", 1, 7, "delete"), TopicSpec("drift.unlisted", 1, 7, "delete"))
    )
    path = tmp_path / "topics.toml"
    path.write_text(
        "replication_factor = 3\n[topics]\n"
        '"drift.listed" = { partitions = 2, retention_days = 30, cleanup_policy = "delete" }\n'
        '"drift.missing" = { partitions = 2, retention_days = 1, cleanup_policy = "delete" }\n',
        encoding="utf-8",
    )
    settings = release_settings(owner_url, bootstrap)
    assert run_topics(settings, "plan", path=path) == 0
    plan = capsys.readouterr().out
    assert "  to create: drift.missing (2 partitions, retention 1 day, cleanup delete)" in plan
    assert (
        "  differs, left as it is: drift.listed (partitions 1 on the broker, 2 in the file; "
        "retention.ms 604800000 on the broker, 2592000000 in the file)"
    ) in plan
    assert "drift.unlisted" in plan.split("not in the file, left alone: ")[1]
    assert "drift.missing" not in broker_topics(bootstrap)

    assert run_topics(settings, "apply", path=path) == 0
    assert "topics apply: 1 created, 1 differing, 0 as the file says" in capsys.readouterr().out
    topics = broker_topics(bootstrap)
    assert topics["drift.missing"].partitions == 2
    assert topics["drift.listed"].partitions == 1
    assert "drift.unlisted" in topics
