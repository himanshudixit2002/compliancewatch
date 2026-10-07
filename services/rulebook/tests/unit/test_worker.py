"""The rulebook worker: the daily transitions sweep, only while publishing is on, and the
consumer of rule.candidate.created, only while the candidate intake is on, on a SQLite inbox and
the memory store."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

from domain_kernel.documents import Clause, DocumentType, document_id_for
from domain_kernel.ids import SourceId
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    SyncProcessedStore,
    processed_event,
)
from py_common.outbox.testing import FakeProducer
from py_common.runtime import IST
from rulebook import worker
from rulebook.application.documents import RegisterDocument
from rulebook.domain.documents import StoredDocument
from rulebook.domain.repository import KnowledgeUnitOfWorkFactory
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.settings import RulebookSettings
from rulebook.testing import rulebook_settings


def _settings(**overrides: Any) -> RulebookSettings:
    return rulebook_settings(rulebook_store="postgres", **overrides)


def test_with_publishing_and_intake_off_only_the_erasure_consumer_runs() -> None:
    components = worker.components(_settings())
    (erasure,) = components.consumers
    assert (erasure.group_id, erasure.topics) == (
        "rulebook.erasure",
        ("tenant.deletion.requested",),
    )
    assert components.periodic == ()


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


# ---------------------------------------------------------------- the candidate intake

EXAMPLES = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "events" / "examples"
DOC_DIGEST = hashlib.sha256(b"example notification for the rulebook worker").hexdigest()
DOC = document_id_for(DOC_DIGEST)
DLQ = "rule.candidate.created.rulebook.rule-candidates.dlq"


@pytest.fixture
def inbox(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'inbox.sqlite'}", poolclass=NullPool)
    processed_event.create(engine)
    yield engine
    engine.dispose()


class Intake:
    """The worker's consumer of rule.candidate.created on a SQLite inbox and the memory store."""

    def __init__(self, inbox: Engine) -> None:
        self.store = MemoryKnowledgeStore()
        self.producer = FakeProducer()
        self.consumer = IdempotentConsumer(
            group_id=worker.CANDIDATES_GROUP_ID,
            store=SyncProcessedStore(inbox, group_id=worker.CANDIDATES_GROUP_ID),
            handler=worker.candidate_handler(units_on=lambda connection: self.store),
            producer=self.producer,
            config=ConsumerConfig(max_handler_attempts=3, retry_backoff_seconds=0),
        )

    def register(self) -> None:
        RegisterDocument(self.store).run(
            StoredDocument(
                document_id=DOC,
                source_id=SourceId(UUID(int=11)),
                sha256=DOC_DIGEST,
                regulator="CBIC",
                doc_type=DocumentType.NOTIFICATION,
                url="https://example.invalid/notification.pdf",
                language="en",
                media_type="application/pdf",
                parser_version="pdf@1",
                fetched_at=datetime(2000, 1, 3, tzinfo=UTC),
            ),
            [Clause("en.p1", "Example notification text.")],
        )


def record(
    example: str, offset: int = 0, *, topic: str = worker.CANDIDATE_TOPIC, **payload: Any
) -> InboundRecord:
    """The contract's example message, its document the registered one, with ``payload``
    changes, as the broker delivers it."""
    message = json.loads(
        (EXAMPLES / "rule.candidate.created" / f"{example}.json").read_text(encoding="utf-8")
    )
    message["topic"] = topic
    message["event_id"] = str(uuid4())
    message["payload"] = {**message["payload"], "document_id": str(DOC), **payload}
    value = json.dumps(message).encode("utf-8")
    return InboundRecord(topic=topic, partition=0, offset=offset, key=b"k", value=value)


def test_with_its_flag_on_the_worker_consumes_rule_candidates() -> None:
    components = worker.components(_settings(rulebook_candidate_intake_enabled=True))
    consumer, erasure = components.consumers
    assert erasure.group_id == "rulebook.erasure"
    assert (consumer.group_id, consumer.topics) == (
        "rulebook.rule-candidates",
        ("rule.candidate.created",),
    )
    assert consumer.dead_letter_topics() == (DLQ,)
    assert components.periodic == (), "publishing stays off"
    assert [c.group_id for c in worker.components(_settings()).consumers] == ["rulebook.erasure"]


async def test_a_candidate_event_becomes_a_candidate_and_its_task_once(inbox: Engine) -> None:
    intake = Intake(inbox)
    intake.register()
    first = record("high-confidence")
    assert await intake.consumer.process(first) is Outcome.PROCESSED
    (candidate,) = intake.store.rule_candidates()
    (task,) = intake.store.review_tasks()
    assert (candidate.regulator, task.candidate_id, task.priority) == (
        "cbic",
        candidate.candidate_id,
        100,
    )
    assert await intake.consumer.process(first) is Outcome.SKIPPED, "the inbox has the event"
    replayed = record("high-confidence", offset=1)
    assert await intake.consumer.process(replayed) is Outcome.PROCESSED
    assert len(intake.store.review_tasks()) == 1, "one task per candidate"
    other = record("unparseable", offset=2)
    assert await intake.consumer.process(other) is Outcome.PROCESSED
    assert [t.priority for t in intake.store.review_tasks()] == [100, 80]
    ignored = record("high-confidence", offset=3, topic="rule.published")
    assert await intake.consumer.process(ignored) is Outcome.PROCESSED
    assert intake.producer.sent == []


async def test_an_unknown_document_or_a_refused_payload_is_dead_lettered(inbox: Engine) -> None:
    intake = Intake(inbox)
    unknown = record("high-confidence")
    assert await intake.consumer.process(unknown) is Outcome.DEAD
    refused = record("high-confidence", offset=1, confidence=7)
    intake.register()
    assert await intake.consumer.process(refused) is Outcome.DEAD
    assert intake.producer.topics() == [DLQ, DLQ]
    assert intake.store.rule_candidates() == []
    assert await intake.consumer.process(unknown) is Outcome.PROCESSED, (
        "a replay takes it in once the document is registered"
    )
