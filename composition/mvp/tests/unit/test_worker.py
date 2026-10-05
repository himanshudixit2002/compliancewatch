"""The worker process: what it hosts by switch and schema, how it stops, and its health."""

import asyncio
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient
from structlog.testing import capture_logs

from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.worker import GROUP_ID as PROFILES_GROUP
from applicability_engine.worker import RULES_GROUP_ID as RULES_GROUP
from cw_mvp import worker as worker_module
from cw_mvp.cli import main as cli_main
from cw_mvp.registry import REGISTRY, entry_named
from cw_mvp.settings import MvpSettings
from cw_mvp.testing import mvp_settings
from cw_mvp.worker import WORKER_CLIENT_ID, build_registry, run_worker, worker_settings
from cw_mvp.worker_health import HealthServer, WorkerHealth, health_app, heartbeat
from obligation.settings import ObligationSettings
from obligation.worker import GROUP_ID as DECISIONS_GROUP
from obligation.worker import RULES_GROUP_ID as OBLIGATION_RULES_GROUP
from obligation.worker import SWEEP_JOB, WINDOW_JOB
from pipeline.settings import PipelineSettings
from py_common.idempotency.purge import JOB_NAME as PURGE_JOB
from py_common.idempotency.schema import IDEMPOTENCY_TABLE
from py_common.outbox.schema import OUTBOX_TABLE
from py_common.runtime import (
    ComponentRegistry,
    TaskComponent,
    WorkerComponents,
    loop_running,
    running_loops,
)
from py_common.settings import Settings
from py_common.temporal.liveness import running

LOCALHOST = "127.0.0.1"
OUTBOX_SCHEMAS = frozenset({"profile", "obligation", "rulebook"})


class FakeInspector:
    """Tables by schema, as a migrated database would have them."""

    def __init__(self, tables: dict[str, set[str]]) -> None:
        self.tables = tables
        self.asked: list[tuple[str | None, str]] = []

    async def __call__(self, settings: Settings, table: str) -> bool:
        self.asked.append((settings.db_schema, table))
        return table in self.tables.get(settings.db_schema or "", set())


def _inspector() -> FakeInspector:
    tables: dict[str, set[str]] = {schema: {OUTBOX_TABLE} for schema in OUTBOX_SCHEMAS}
    tables["profile"].add(IDEMPOTENCY_TABLE)
    return FakeInspector(tables)


def _root(**overrides: Any) -> MvpSettings:
    values: dict[str, Any] = {"mvp_host": LOCALHOST, "log_level": "WARNING"}
    values.update(overrides)
    return mvp_settings(**values)


async def test_with_both_switches_off_no_kafka_or_temporal_work_is_hosted() -> None:
    inspector = _inspector()
    hosted = await build_registry(_root(), probe=inspector)
    assert hosted.consumer_groups() == ()
    assert hosted.task_queues() == ()
    assert all(not entry.components.relays for entry in hosted.hosted)
    assert set(hosted.loops()) == {
        "notification/notification-dispatch",
        "notification/notification-retention",
        f"profile/{PURGE_JOB}",
    }
    assert ("profile", OUTBOX_TABLE) not in inspector.asked


async def test_relays_start_only_for_schemas_with_an_outbox() -> None:
    hosted = await build_registry(_root(worker_kafka_enabled=True), probe=_inspector())
    relaying = {entry.service for entry in hosted.hosted if entry.components.relays}
    assert relaying == OUTBOX_SCHEMAS
    assert hosted.consumer_groups() == (
        PROFILES_GROUP,
        RULES_GROUP,
        DECISIONS_GROUP,
        OBLIGATION_RULES_GROUP,
        "notification.obligations",
    )
    assert "profile/outbox-relay" in hosted.loops()
    assert hosted.task_queues() == ()


async def test_obligation_consumes_decisions_with_kafka_and_sweeps_behind_its_own_switch() -> None:
    sweeping = {"obligation": {"obligation_sweep_enabled": True}}
    neither = await build_registry(_root(), probe=_inspector())
    assert not [loop for loop in neither.loops() if loop.startswith("obligation/")]
    kafka = await build_registry(_root(worker_kafka_enabled=True), probe=_inspector())
    assert DECISIONS_GROUP in kafka.consumer_groups()
    assert f"obligation/{SWEEP_JOB}" not in kafka.loops()
    sweep = await build_registry(_root(), probe=_inspector(), service_overrides=sweeping)
    assert f"obligation/{SWEEP_JOB}" in sweep.loops()
    assert f"obligation/{WINDOW_JOB}" in sweep.loops()
    assert DECISIONS_GROUP not in sweep.consumer_groups()
    (obligation,) = [entry for entry in sweep.hosted if entry.service == "obligation"]
    assert isinstance(obligation.settings, ObligationSettings)
    assert obligation.settings.rulebook_url == _root().mvp_internal_url


async def test_obligation_consumes_rule_events_with_kafka_whatever_its_flag() -> None:
    for enabled in (False, True):
        hosted = await build_registry(
            _root(worker_kafka_enabled=True),
            probe=_inspector(),
            service_overrides={"obligation": {"obligation_rule_events_enabled": enabled}},
        )
        assert OBLIGATION_RULES_GROUP in hosted.consumer_groups()
        assert f"obligation/consumer:{OBLIGATION_RULES_GROUP}" in hosted.loops()
        (obligation,) = [entry for entry in hosted.hosted if entry.service == "obligation"]
        assert isinstance(obligation.settings, ObligationSettings)
        assert obligation.settings.obligation_rule_events_enabled is enabled


async def test_the_engine_consumes_profile_updates_with_kafka_whatever_its_recompute_switch() -> (
    None
):
    off = await build_registry(_root(worker_kafka_enabled=True), probe=_inspector())
    on = await build_registry(
        _root(worker_kafka_enabled=True),
        probe=_inspector(),
        service_overrides={"applicability-engine": {"applicability_recompute_enabled": True}},
    )
    for hosted in (off, on):
        assert PROFILES_GROUP in hosted.consumer_groups()
        assert f"applicability-engine/consumer:{PROFILES_GROUP}" in hosted.loops()
    (engine,) = [entry for entry in on.hosted if entry.service == "applicability-engine"]
    assert isinstance(engine.settings, ApplicabilityEngineSettings)
    assert engine.settings.applicability_recompute_enabled
    assert engine.settings.profile_url == _root().mvp_internal_url
    neither = await build_registry(_root(), probe=_inspector())
    assert PROFILES_GROUP not in neither.consumer_groups()


async def test_a_service_on_its_memory_store_is_left_to_the_app_process() -> None:
    inspector = _inspector()
    in_memory = {"obligation": {"obligation_store": "memory", "obligation_sweep_enabled": True}}
    with capture_logs() as logs:
        hosted = await build_registry(
            _root(worker_kafka_enabled=True), probe=inspector, service_overrides=in_memory
        )
    assert "obligation" not in {entry.service for entry in hosted.hosted}
    assert DECISIONS_GROUP not in hosted.consumer_groups()
    assert not [asked for asked in inspector.asked if asked[0] == "obligation"]
    assert {"profile", "rulebook", "notification"} <= {entry.service for entry in hosted.hosted}
    (skipped,) = [log for log in logs if log["event"] == "worker.service_skipped"]
    assert skipped["service"] == "obligation"
    assert "CW_OBLIGATION_STORE=memory" in skipped["reason"]


async def test_temporal_workers_start_with_their_switch() -> None:
    hosted = await build_registry(_root(worker_temporal_enabled=True), probe=_inspector())
    assert hosted.task_queues() == ("applicability", "pipeline")
    assert hosted.consumer_groups() == ()


async def test_the_engine_starts_fan_outs_from_rule_events_with_kafka_whatever_its_flag() -> None:
    for enabled in (False, True):
        hosted = await build_registry(
            _root(worker_kafka_enabled=True, worker_temporal_enabled=True),
            probe=_inspector(),
            service_overrides={"applicability-engine": {"applicability_fanout_enabled": enabled}},
        )
        assert RULES_GROUP in hosted.consumer_groups()
        assert f"applicability-engine/consumer:{RULES_GROUP}" in hosted.loops()
        assert "applicability" in hosted.task_queues()
        (engine,) = [entry for entry in hosted.hosted if entry.service == "applicability-engine"]
        assert isinstance(engine.settings, ApplicabilityEngineSettings)
        assert engine.settings.applicability_fanout_enabled is enabled
        assert engine.settings.rulebook_url == _root().mvp_internal_url


async def test_each_service_calls_the_others_at_the_internal_url_as_the_worker() -> None:
    hosted = await build_registry(
        _root(worker_temporal_enabled=True),
        internal_url="http://mvp-app:8080",
        probe=_inspector(),
    )
    (pipeline_hosted,) = [entry for entry in hosted.hosted if entry.service == "pipeline"]
    pipeline = pipeline_hosted.settings
    assert isinstance(pipeline, PipelineSettings)
    assert pipeline.service_client_id == WORKER_CLIENT_ID
    assert pipeline.rulebook_url == "http://mvp-app:8080"
    assert pipeline.identity_url == "http://mvp-app:8080"
    named = worker_settings(
        entry_named("qa"), _root(service_client_id="ops"), internal_url="http://x:1"
    )
    assert named.service_client_id == "ops"


async def test_the_rulebook_sweep_runs_while_publishing_is_on() -> None:
    hosted = await build_registry(
        _root(),
        probe=_inspector(),
        service_overrides={"rulebook": {"rulebook_publish_enabled": True}},
    )
    assert "rulebook/rulebook-transitions" in hosted.loops()


async def test_overrides_must_name_registered_services() -> None:
    with pytest.raises(KeyError, match="nowhere"):
        await build_registry(_root(), probe=_inspector(), service_overrides={"nowhere": {}})


def _hosting(*tasks: TaskComponent) -> ComponentRegistry:
    return ComponentRegistry().register("demo", _root(), WorkerComponents(tasks=tasks))


async def test_with_nothing_hosted_only_the_health_loop_runs() -> None:
    stop = asyncio.Event()
    running_worker = asyncio.create_task(
        run_worker(_root(), stop, hosted=ComponentRegistry(), health_port=0)
    )
    await asyncio.sleep(0.2)
    assert not running_worker.done()
    stop.set()
    await asyncio.wait_for(running_worker, timeout=10)


async def test_one_failing_loop_stops_the_others_and_the_worker_fails() -> None:
    async def steady(stop: asyncio.Event) -> None:
        await stop.wait()

    async def failing(_: asyncio.Event) -> None:
        await asyncio.sleep(0.05)
        raise RuntimeError("broker gone")

    hosted = _hosting(TaskComponent("steady", steady), TaskComponent("failing", failing))
    stop = asyncio.Event()
    with pytest.raises(ExceptionGroup) as failure:
        await asyncio.wait_for(run_worker(_root(), stop, hosted=hosted, health_port=0), 10)
    assert failure.group_contains(RuntimeError, match="broker gone")
    assert stop.is_set()
    assert running_loops() == ()


def test_the_command_exits_one_when_a_loop_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing(root: MvpSettings, *, internal_url: str | None) -> None:
        raise ExceptionGroup("worker", [RuntimeError("broker gone")])

    monkeypatch.setattr(worker_module, "serve", failing)
    assert worker_module.main(settings=_root()) == 1


def test_the_command_exits_zero_after_a_clean_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str | None] = []

    async def clean(root: MvpSettings, *, internal_url: str | None) -> None:
        urls.append(internal_url)

    monkeypatch.setattr(worker_module, "serve", clean)
    assert worker_module.main(internal_url="http://app:8080", settings=_root()) == 0
    assert urls == ["http://app:8080"]


def test_cw_mvp_worker_passes_the_internal_url(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []

    def fake_main(*, internal_url: str | None) -> int:
        seen.append(internal_url)
        return 0

    monkeypatch.setattr(worker_module, "main", fake_main)
    assert cli_main(["worker", "--internal-url", "http://mvp-app:8080"]) == 0
    assert cli_main(["worker"]) == 0
    assert seen == ["http://mvp-app:8080", None]


async def test_serve_hosts_the_registry_until_a_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[ComponentRegistry] = []

    async def fake_build(root: MvpSettings, *, internal_url: str | None) -> ComponentRegistry:
        return ComponentRegistry()

    async def fake_run(
        root: MvpSettings, stop: asyncio.Event, *, hosted: ComponentRegistry
    ) -> None:
        ran.append(hosted)

    monkeypatch.setattr(worker_module, "build_registry", fake_build)
    monkeypatch.setattr(worker_module, "run_worker", fake_run)
    monkeypatch.setattr(worker_module, "install_stop_signals", lambda stop: None)
    await worker_module.serve(_root())
    assert ran == [ComponentRegistry()]


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


def _health(clock: Clock) -> WorkerHealth:
    return WorkerHealth(
        loops=("notification/notification-dispatch",),
        task_queues=("pipeline",),
        stale_after_seconds=30.0,
        clock=clock,
    )


def test_health_is_ok_while_every_loop_runs_and_the_heartbeat_is_fresh(clock: Clock) -> None:
    health = _health(clock)
    client = TestClient(health_app(health))
    assert client.get("/health").status_code == 503
    health.beat(loops=["notification/notification-dispatch"], task_queues=["pipeline"])
    clock.now += 29
    assert client.get("/health").status_code == 200
    detail = client.get("/loops").json()
    assert detail["loops"] == {"notification/notification-dispatch": True}
    assert detail["task_queues"] == {"pipeline": True}
    assert detail["heartbeat_age_seconds"] == 29.0


def test_health_turns_503_on_a_stale_heartbeat(clock: Clock) -> None:
    health = _health(clock)
    health.beat(loops=["notification/notification-dispatch"], task_queues=["pipeline"])
    clock.now += 31
    response = TestClient(health_app(health)).get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"


def test_health_turns_503_when_a_hosted_loop_stopped(clock: Clock) -> None:
    health = _health(clock)
    health.beat(loops=[], task_queues=["pipeline"])
    client = TestClient(health_app(health))
    assert client.get("/health").status_code == 503
    assert client.get("/loops").json()["loops"] == {"notification/notification-dispatch": False}


async def test_the_heartbeat_records_the_running_loops_and_queues(clock: Clock) -> None:
    health = _health(clock)
    stop = asyncio.Event()
    with loop_running("notification/notification-dispatch"), running("pipeline"):
        beating = asyncio.create_task(heartbeat(health, stop, interval=0.01))
        await asyncio.sleep(0.05)
        assert health.report().healthy
    await asyncio.sleep(0.05)
    assert not health.report().healthy
    stop.set()
    await asyncio.wait_for(beating, timeout=5)


@pytest.fixture
def health_server(clock: Clock) -> Iterator[HealthServer]:
    health = _health(clock)
    health.beat(loops=["notification/notification-dispatch"], task_queues=["pipeline"])
    server = HealthServer(health_app(health), LOCALHOST, 0)
    server.start()
    try:
        yield server
    finally:
        server.stop()


def test_the_health_app_answers_on_its_own_thread(health_server: HealthServer) -> None:
    response = httpx2.get(f"http://{LOCALHOST}:{health_server.port}/health", timeout=5)
    assert response.status_code == 200


def test_every_service_with_background_work_is_hosted_by_the_worker() -> None:
    assert {entry.name for entry in REGISTRY if entry.components is not None} == {
        "applicability-engine",
        "notification",
        "obligation",
        "pipeline",
        "rulebook",
    }


def test_a_heartbeat_must_come_sooner_than_it_goes_stale() -> None:
    with pytest.raises(ValidationError, match="STALE_SECONDS"):
        mvp_settings(mvp_worker_heartbeat_seconds=10, mvp_worker_stale_seconds=10)
