"""The entity review queue numbers: the domain type, the memory store, the use case, and the
OpenTelemetry gauges read through an in-memory metric reader."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint
from structlog.testing import capture_logs

from domain_kernel.ids import ClauseId, DocumentId
from domain_kernel.knowledge import EntityType
from py_common.telemetry import Telemetry
from rulebook.application.review import ReadReviewQueueStats
from rulebook.domain.alignment import ReviewReason
from rulebook.domain.review import EntityRejectReason, EntityReviewItem, ReviewQueueStats
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.infrastructure.review_metrics import (
    OLDEST_OPEN_AGE,
    OPEN_ITEMS,
    ReviewQueueGauges,
    register_review_queue_gauges,
)
from rulebook.main import build_app, install_review_metrics
from rulebook.testing import rulebook_settings

T0 = datetime(2026, 9, 28, 12, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def item(entity_type: EntityType, name: str = "x") -> EntityReviewItem:
    return EntityReviewItem(
        review_id=uuid4(),
        document_id=DocumentId.new(),
        clause_id=ClauseId.new(),
        entity_type=entity_type,
        mention_text=name,
        span_start=0,
        span_end=len(name),
        proposed_name=name,
        reason=ReviewReason.NO_MATCH,
        extractor="grammar@1",
    )


def queue(store: MemoryKnowledgeStore, *items: EntityReviewItem) -> None:
    with store() as uow:
        for queued in items:
            assert uow.reviews.enqueue(queued)


def points(reader: InMemoryMetricReader) -> dict[str, dict[str, float]]:
    """Each gauge's values keyed by its ``entity_type`` attribute ("" when it has none)."""
    found: dict[str, dict[str, float]] = {}
    data = reader.get_metrics_data()
    if data is None:
        return found
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                values = found.setdefault(metric.name, {})
                for point in metric.data.data_points:
                    assert isinstance(point, NumberDataPoint)
                    attributes = point.attributes or {}
                    values[str(attributes.get("entity_type", ""))] = point.value
    return found


def test_stats_fill_every_type_and_age_the_oldest_item() -> None:
    stats = ReviewQueueStats({EntityType.FORM: 2, EntityType.SECTION: 1}, T0)
    assert stats.open_items == 3
    counts = stats.counts()
    assert set(counts) == set(EntityType)
    assert (counts[EntityType.FORM], counts[EntityType.SECTION], counts[EntityType.STATE]) == (
        2,
        1,
        0,
    )
    assert stats.oldest_open_age_seconds(T0 + timedelta(hours=2)) == 7200.0
    assert stats.oldest_open_age_seconds(T0 - timedelta(seconds=5)) == 0.0, "never negative"
    empty = ReviewQueueStats({}, None)
    assert (empty.open_items, empty.oldest_open_age_seconds(T0)) == (0, 0.0)


def test_memory_store_counts_open_items_from_when_they_were_queued() -> None:
    clock = Clock()
    store = MemoryKnowledgeStore(clock=clock)
    assert ReadReviewQueueStats(store).run() == ReviewQueueStats({}, None)
    first = item(EntityType.FORM)
    queue(store, first)
    clock.advance(hours=1)
    queue(store, item(EntityType.FORM), item(EntityType.SECTION))
    with store() as uow:
        assert not uow.reviews.enqueue(first), "a repeat keeps the first queued time"
    stats = ReadReviewQueueStats(store).run()
    assert stats.by_type == {EntityType.FORM: 2, EntityType.SECTION: 1}
    assert stats.oldest_open_at == T0

    with store() as uow:
        uow.reviews.save(
            first.reject(EntityRejectReason.TEXT_ARTIFACT, decided_by="analyst", at=clock())
        )
    stats = ReadReviewQueueStats(store).run()
    assert stats.by_type == {EntityType.FORM: 1, EntityType.SECTION: 1}
    assert stats.oldest_open_at == T0 + timedelta(hours=1), "a decided item no longer counts"


def test_gauges_report_counts_per_type_and_the_oldest_age() -> None:
    clock = Clock()
    store = MemoryKnowledgeStore(clock=clock)
    queue(store, item(EntityType.FORM), item(EntityType.FORM), item(EntityType.STATE))
    clock.advance(hours=50)
    reader = InMemoryMetricReader()
    register_review_queue_gauges(
        ReadReviewQueueStats(store).run,
        clock,
        MeterProvider(metric_readers=[reader]).get_meter("t"),
    )
    found = points(reader)
    assert found[OPEN_ITEMS]["form"] == 2
    assert found[OPEN_ITEMS]["state"] == 1
    assert found[OPEN_ITEMS]["section"] == 0
    assert set(found[OPEN_ITEMS]) == {entity_type.value for entity_type in EntityType}
    assert found[OLDEST_OPEN_AGE] == {"": 50 * 3600.0}


def test_one_reading_serves_both_gauges_until_it_is_a_minute_old() -> None:
    clock = Clock()
    reads: list[datetime] = []

    def read() -> ReviewQueueStats:
        reads.append(clock())
        return ReviewQueueStats({EntityType.FORM: len(reads)}, T0)

    gauges = ReviewQueueGauges(read, clock)
    reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[reader]).get_meter("t")
    meter.create_observable_gauge(OPEN_ITEMS, callbacks=[gauges.open_items])
    meter.create_observable_gauge(OLDEST_OPEN_AGE, callbacks=[gauges.oldest_open_age])

    assert points(reader)[OPEN_ITEMS]["form"] == 1
    clock.advance(seconds=59)
    found = points(reader)
    assert found[OPEN_ITEMS]["form"] == 1, "still the cached reading"
    assert found[OLDEST_OPEN_AGE] == {"": 59.0}, "the age moves with the clock"
    clock.advance(seconds=1)
    assert points(reader)[OPEN_ITEMS]["form"] == 2
    assert reads == [T0, T0 + timedelta(seconds=60)]


def test_a_failed_read_is_logged_and_reports_nothing_until_the_next_read() -> None:
    clock = Clock()
    failures = [RuntimeError("database unavailable")]

    def read() -> ReviewQueueStats:
        if failures:
            raise failures.pop()
        return ReviewQueueStats({EntityType.FORM: 4}, T0)

    reader = InMemoryMetricReader()
    register_review_queue_gauges(read, clock, MeterProvider(metric_readers=[reader]).get_meter("t"))
    with capture_logs() as logs:
        found = points(reader)
    assert found.get(OPEN_ITEMS, {}) == {}
    assert found.get(OLDEST_OPEN_AGE, {}) == {}
    [line] = logs
    assert line["event"] == "review_metrics.read_failed"
    assert line["error"] == "RuntimeError: database unavailable"
    clock.advance(seconds=60)
    assert points(reader)[OPEN_ITEMS]["form"] == 4


def test_the_app_registers_the_gauges_only_when_telemetry_is_on() -> None:
    app = build_app(rulebook_settings())
    assert app.state.telemetry.enabled is False
    assert install_review_metrics(app, app.state.wiring) is False

    reader = InMemoryMetricReader()
    app.state.telemetry = Telemetry(
        enabled=True,
        service_name="rulebook",
        endpoint="http://collector:4317",
        meter_provider=MeterProvider(metric_readers=[reader]),
    )
    assert install_review_metrics(app, app.state.wiring) is True
    found = points(reader)
    assert found[OPEN_ITEMS]["form"] == 0
    assert found[OLDEST_OPEN_AGE] == {"": 0.0}
