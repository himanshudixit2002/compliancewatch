"""Topics as code: the file's rules, the plan against a broker, and an apply that only creates."""

from collections.abc import Collection, Mapping, Sequence
from types import TracebackType
from typing import Self

import pytest

from cw_mvp.topics import (
    DAY_MS,
    BrokerTopic,
    TopicsFile,
    TopicsFileError,
    TopicSpec,
    apply,
    make_plan,
    parse,
    plan,
)

FILE = """
replication_factor = 3

[topics]
"profile.updated" = { partitions = 3, retention_days = 7, cleanup_policy = "delete" }
"rule.published" = { partitions = 1, retention_days = 30, cleanup_policy = "delete" }

[topics."rule.published.obligation.rules.dlq"]
partitions = 1
retention_days = 30
cleanup_policy = "delete"
"""


class FakeAdmin:
    """A broker of ``brokers`` nodes holding ``topics``; records what it was asked to make."""

    def __init__(self, topics: Mapping[str, BrokerTopic], brokers: int = 1) -> None:
        self.held = dict(topics)
        self.nodes = brokers
        self.created: list[tuple[str, int, int, dict[str, str]]] = []
        self.asked_configs: list[str] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        return None

    async def brokers(self) -> int:
        return self.nodes

    async def topics(self, with_configs: Collection[str]) -> Mapping[str, BrokerTopic]:
        self.asked_configs = sorted(with_configs)
        return dict(self.held)

    async def create(self, topics: Sequence[TopicSpec], replication_factor: int) -> None:
        for spec in topics:
            self.created.append((spec.name, spec.partitions, replication_factor, spec.configs()))
            self.held[spec.name] = BrokerTopic(spec.name, spec.partitions, spec.configs())


def broker_topic(name: str, partitions: int, days: int = 7, policy: str = "delete") -> BrokerTopic:
    return BrokerTopic(
        name, partitions, {"retention.ms": str(days * DAY_MS), "cleanup.policy": policy}
    )


def test_the_file_parses_in_its_order_with_the_settings_kafka_takes() -> None:
    wanted = parse(FILE)
    assert wanted.replication_factor == 3
    assert [topic.name for topic in wanted.topics] == [
        "profile.updated",
        "rule.published",
        "rule.published.obligation.rules.dlq",
    ]
    assert wanted.topics[1].configs() == {"retention.ms": "2592000000", "cleanup.policy": "delete"}
    assert wanted.topics[0].describe() == "3 partitions, retention 7 days, cleanup delete"


def entry(name: str = "a", **values: object) -> str:
    """One topic's line, the defaults overridden by ``values`` (None drops a key)."""
    fields: dict[str, object] = {"partitions": 1, "retention_days": 1, "cleanup_policy": "delete"}
    fields.update(values)
    inline = ", ".join(
        f"{key} = {value!r}".replace("'", '"') for key, value in fields.items() if value is not None
    )
    return f'"{name}" = {{ {inline} }}'


def topics_file(*entries: str, head: str = "replication_factor = 1") -> str:
    return "\n".join([head, "[topics]", *entries])


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        (topics_file(entry(), head=""), "replication_factor must be a whole number"),
        (
            topics_file(entry(), head="replication_factor = 0"),
            "replication_factor must be a whole number",
        ),
        (topics_file(), "[topics] must name at least one topic"),
        (topics_file(entry("A.b")), "'A.b' is not a topic name"),
        (topics_file(entry(partitions=0)), "a: partitions must be a whole number of at least 1"),
        (
            topics_file(entry(retention_days=0)),
            "a: retention_days must be a whole number of at least 1",
        ),
        (topics_file(entry(cleanup_policy="keep")), "a: cleanup_policy must be one of"),
        (topics_file(entry(cleanup_policy=None)), "a: cleanup_policy is missing"),
        (topics_file(entry(size=2)), "a: unknown key 'size'"),
        (
            topics_file(entry(), head="replication_factor = 1\nextra = true"),
            "unknown keys ['extra']",
        ),
        ("replication_factor = [", "topics.toml is not TOML"),
    ],
)
def test_a_malformed_file_is_refused_with_what_is_wrong(text: str, problem: str) -> None:
    with pytest.raises(TopicsFileError) as raised:
        parse(text)
    assert problem in str(raised.value)


def test_every_problem_is_reported_at_once() -> None:
    text = topics_file(
        entry("a", partitions=0), entry("b", cleanup_policy="keep"), head="replication_factor = 0"
    )
    with pytest.raises(TopicsFileError) as raised:
        parse(text)
    assert str(raised.value).count(";") == 2


def test_the_plan_creates_the_missing_reports_drift_and_leaves_unlisted_topics_alone() -> None:
    wanted = parse(FILE)
    existing = {
        "profile.updated": broker_topic("profile.updated", 1),
        "rule.published": broker_topic("rule.published", 1, days=30),
        "obligation.created.dlq": broker_topic("obligation.created.dlq", 1),
        "_schemas": broker_topic("_schemas", 1),
    }
    result = plan(wanted, existing, brokers=1)
    assert [spec.name for spec in result.create] == ["rule.published.obligation.rules.dlq"]
    assert [drift.name for drift in result.drift] == ["profile.updated"]
    assert result.drift[0].differences == ("partitions 1 on the broker, 3 in the file",)
    assert result.matching == ("rule.published",)
    assert result.unlisted == ("obligation.created.dlq",)
    assert result.replication_factor == 1
    assert result.summary() == (
        "1 to create, 1 differ, 1 as the file says, replication factor 1 (1 broker)"
    )
    assert result.lines() == [
        "  to create: rule.published.obligation.rules.dlq (1 partition, retention 30 days, "
        "cleanup delete)",
        "  differs, left as it is: profile.updated (partitions 1 on the broker, 3 in the file)",
        "  as the file says: 1 topics",
        "  not in the file, left alone: obligation.created.dlq",
    ]


def test_settings_that_differ_are_drift_and_unreported_settings_are_not() -> None:
    wanted = parse(FILE)
    existing = {
        "profile.updated": BrokerTopic("profile.updated", 3, {"cleanup.policy": "compact"}),
        "rule.published": BrokerTopic("rule.published", 1, {}),
    }
    result = plan(wanted, existing, brokers=3)
    assert [drift.differences for drift in result.drift] == [
        ("cleanup.policy compact on the broker, delete in the file",)
    ]
    assert "rule.published" in result.matching
    assert result.replication_factor == 3


@pytest.mark.parametrize(("brokers", "factor"), [(0, 1), (1, 1), (2, 2), (3, 3), (6, 3)])
def test_the_replication_factor_is_the_files_capped_at_the_brokers(
    brokers: int, factor: int
) -> None:
    assert plan(parse(FILE), {}, brokers=brokers).replication_factor == factor


async def test_apply_creates_only_what_is_missing_and_a_second_apply_creates_nothing() -> None:
    wanted = parse(FILE)
    admin = FakeAdmin({"profile.updated": broker_topic("profile.updated", 1)}, brokers=1)
    first = await apply(admin, wanted)
    assert [name for name, *_ in admin.created] == [
        "rule.published",
        "rule.published.obligation.rules.dlq",
    ]
    assert admin.created[0] == (
        "rule.published",
        1,
        1,
        {"retention.ms": "2592000000", "cleanup.policy": "delete"},
    )
    assert admin.held["profile.updated"].partitions == 1
    assert [drift.name for drift in first.drift] == ["profile.updated"]
    assert first.lines(applied=True)[0].startswith("  created: rule.published (")
    assert first.summary(applied=True).startswith("2 created, 1 differ")

    admin.created.clear()
    second = await apply(admin, wanted)
    assert admin.created == []
    assert second.create == ()
    assert sorted(second.matching) == ["rule.published", "rule.published.obligation.rules.dlq"]


async def test_the_plan_asks_the_broker_for_the_settings_of_the_files_topics_only() -> None:
    admin = FakeAdmin({}, brokers=3)
    result = await make_plan(admin, parse(FILE))
    assert admin.asked_configs == sorted(parse(FILE).names)
    assert len(result.create) == 3
    assert admin.created == []


def test_a_topics_file_names_its_topics() -> None:
    wanted = TopicsFile(1, (TopicSpec("a", 1, 1, "delete"),))
    assert wanted.names == frozenset({"a"})
