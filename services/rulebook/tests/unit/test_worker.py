"""The rulebook worker: the daily transitions sweep, only while publishing is on."""

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from typing import Any

import pytest

from py_common.runtime import IST
from rulebook import worker
from rulebook.domain.repository import KnowledgeUnitOfWorkFactory
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.settings import RulebookSettings
from rulebook.testing import rulebook_settings


def _settings(**overrides: Any) -> RulebookSettings:
    return rulebook_settings(rulebook_store="postgres", **overrides)


def test_with_publishing_off_there_is_nothing_to_run() -> None:
    assert worker.components(_settings()).is_empty


def test_the_worker_refuses_the_memory_store() -> None:
    with pytest.raises(ValueError, match="CW_RULEBOOK_STORE=postgres"):
        worker.components(rulebook_settings(rulebook_publish_enabled=True))


def test_with_publishing_on_the_sweep_runs_just_after_midnight_in_india() -> None:
    (job,) = worker.components(_settings(rulebook_publish_enabled=True)).periodic
    assert job.name == worker.TRANSITIONS_JOB
    assert job.next_run is not None
    due = job.next_run(datetime(2026, 10, 1, 12, 0, tzinfo=UTC))
    assert due.astimezone(IST) == datetime(2026, 10, 2, 0, 5, tzinfo=IST)


def test_a_sweep_runs_on_the_store_it_opens() -> None:
    store = MemoryKnowledgeStore()
    opened: list[KnowledgeUnitOfWorkFactory] = []

    @contextmanager
    def units() -> Iterator[KnowledgeUnitOfWorkFactory]:
        opened.append(store)
        with nullcontext(store) as open_store:
            yield open_store

    worker.transitions_job(units)()
    assert opened == [store]


def test_the_postgres_store_is_disposed_after_each_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    disposed: list[str] = []

    class Engine:
        def dispose(self) -> None:
            disposed.append("disposed")

    class Factory:
        engine = Engine()

    urls: list[str] = []

    def from_url(url: str) -> Factory:
        urls.append(url)
        return Factory()

    monkeypatch.setattr(PostgresKnowledgeUnitOfWorkFactory, "from_url", from_url)
    settings = _settings(database_url="postgresql+psycopg://cw@db/cw")
    with worker.postgres_units(settings)() as factory:
        assert isinstance(factory, Factory)
    assert urls == ["postgresql+psycopg://cw@db/cw"]
    assert disposed == ["disposed"]


def test_python_m_rulebook_worker_runs_the_components(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[tuple[object, object]] = []
    monkeypatch.setattr(worker, "run_worker_process", lambda s, c, *, version: ran.append((s, c)))
    worker.main()
    ((settings, components),) = ran
    assert isinstance(settings, RulebookSettings)
    assert settings.service_name == "rulebook-worker"
    assert components is worker.components
