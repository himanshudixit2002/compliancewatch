"""Kafka topics as code: ``composition/mvp/topics.toml`` against the broker.

The file lists every contract topic (``packages/contracts/events/schemas``) and the dead-letter
topic of every consumer group the worker hosts (``<topic>.<group>.dlq``), each with its
partitions, retention and cleanup policy, and one replication factor for all of them;
``tests/unit/test_topics_file.py`` fails when a topic is missing or one is neither.

``cw-mvp topics plan`` compares the file with the broker of the ``CW_KAFKA_*`` settings (with
SASL and TLS for a managed cluster, ``py_common.kafka.KafkaClientConfig``), and
``cw-mvp topics apply`` creates the topics the broker lacks; ``cw-mvp release`` runs the apply.
Neither deletes or changes a topic. One the file does not list is left alone. One whose
partitions or settings differ from the file is reported and left as it is: adding partitions
moves keys between them, so an operator decides (``rpk topic add-partitions``,
``rpk topic alter-config``).

The replication factor is capped at the brokers the cluster reports, so the dev stack's single
Redpanda gets 1 where a managed cluster gets the file's 3.
"""

import re
import tomllib
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Protocol, Self

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.admin.config_resource import ConfigResource, ConfigResourceType
from aiokafka.errors import for_code

import cw_mvp
from py_common.kafka import KafkaClientConfig

TOPICS_FILE: Final = Path(cw_mvp.__file__).resolve().parents[2] / "topics.toml"
"""``composition/mvp/topics.toml``, beside the package's sources in a checkout and the image."""
TOPIC_NAME: Final = re.compile(r"[a-z0-9][a-z0-9._-]{0,248}")
CLEANUP_POLICIES: Final = frozenset({"delete", "compact", "compact,delete"})
TOPIC_KEYS: Final = frozenset({"partitions", "retention_days", "cleanup_policy"})
DAY_MS: Final = 86_400_000
RETENTION: Final = "retention.ms"
CLEANUP: Final = "cleanup.policy"
TOPIC_ALREADY_EXISTS: Final = 36
CLIENT_ID: Final = "cw-mvp-topics"
REQUEST_TIMEOUT_MS: Final = 30_000


class TopicsFileError(ValueError):
    """``topics.toml`` is malformed; the message lists every finding."""


class TopicsError(RuntimeError):
    """The broker refused to create a topic."""


@dataclass(frozen=True, slots=True)
class TopicSpec:
    name: str
    partitions: int
    retention_days: int
    cleanup_policy: str

    @property
    def retention_ms(self) -> int:
        return self.retention_days * DAY_MS

    def configs(self) -> dict[str, str]:
        """The topic settings it is made with, by their Kafka names."""
        return {RETENTION: str(self.retention_ms), CLEANUP: self.cleanup_policy}

    def describe(self) -> str:
        days = "day" if self.retention_days == 1 else "days"
        return (
            f"{self.partitions} partition{'s' if self.partitions != 1 else ''}, retention "
            f"{self.retention_days} {days}, cleanup {self.cleanup_policy}"
        )


@dataclass(frozen=True, slots=True)
class TopicsFile:
    replication_factor: int
    topics: tuple[TopicSpec, ...]

    @property
    def names(self) -> frozenset[str]:
        return frozenset(topic.name for topic in self.topics)


def parse(text: str) -> TopicsFile:
    """The file's topics in its order; every problem is reported at once."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise TopicsFileError(f"topics.toml is not TOML: {exc}") from None
    problems: list[str] = []
    unknown = sorted(set(data) - {"replication_factor", "topics"})
    if unknown:
        problems.append(f"unknown keys {unknown}; the file has replication_factor and [topics]")
    factor = data.get("replication_factor")
    if not _positive(factor):
        problems.append("replication_factor must be a whole number of at least 1")
    raw = data.get("topics")
    if not isinstance(raw, dict) or not raw:
        problems.append("[topics] must name at least one topic")
        raw = {}
    topics: list[TopicSpec] = []
    for name, values in raw.items():
        spec, found = _topic(name, values)
        problems.extend(found)
        if spec is not None:
            topics.append(spec)
    if problems:
        raise TopicsFileError("; ".join(problems))
    return TopicsFile(replication_factor=int(data["replication_factor"]), topics=tuple(topics))


def _positive(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _topic(name: str, values: object) -> tuple[TopicSpec | None, list[str]]:
    if not TOPIC_NAME.fullmatch(name):
        return None, [f"{name!r} is not a topic name (lower case, digits, '.', '_' and '-')"]
    if not isinstance(values, dict):
        return None, [f"{name}: give partitions, retention_days and cleanup_policy"]
    problems = [f"{name}: unknown key {key!r}" for key in sorted(set(values) - TOPIC_KEYS)]
    problems += [f"{name}: {key} is missing" for key in sorted(TOPIC_KEYS - set(values))]
    partitions, days, policy = (
        values.get("partitions"),
        values.get("retention_days"),
        values.get("cleanup_policy"),
    )
    if "partitions" in values and not _positive(partitions):
        problems.append(f"{name}: partitions must be a whole number of at least 1")
    if "retention_days" in values and not _positive(days):
        problems.append(f"{name}: retention_days must be a whole number of at least 1")
    if "cleanup_policy" in values and policy not in CLEANUP_POLICIES:
        problems.append(f"{name}: cleanup_policy must be one of {sorted(CLEANUP_POLICIES)}")
    if problems:
        return None, problems
    spec = TopicSpec(
        name,
        partitions=int(values["partitions"]),
        retention_days=int(values["retention_days"]),
        cleanup_policy=str(values["cleanup_policy"]),
    )
    return spec, []


def load(path: Path = TOPICS_FILE) -> TopicsFile:
    return parse(path.read_text(encoding="utf-8"))


@dataclass(frozen=True, slots=True)
class BrokerTopic:
    """A topic as the broker reports it: its partitions and the settings ``cw-mvp`` manages
    (only for the topics the file lists)."""

    name: str
    partitions: int
    configs: Mapping[str, str]


class TopicAdmin(Protocol):
    """The broker's topics, opened with ``async with``."""

    async def __aenter__(self) -> "TopicAdmin": ...

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None: ...

    async def brokers(self) -> int: ...

    async def topics(self, with_configs: Collection[str]) -> Mapping[str, BrokerTopic]: ...

    async def create(self, topics: Sequence[TopicSpec], replication_factor: int) -> None: ...


@dataclass(frozen=True, slots=True)
class Drift:
    name: str
    differences: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TopicPlan:
    """What the broker lacks (``create``), what differs from the file (``drift``, left as it
    is), what matches, and the topics the file does not list (left alone)."""

    create: tuple[TopicSpec, ...]
    drift: tuple[Drift, ...]
    matching: tuple[str, ...]
    unlisted: tuple[str, ...]
    brokers: int
    replication_factor: int

    def lines(self, *, applied: bool = False) -> list[str]:
        verb = "created" if applied else "to create"
        lines = [f"  {verb}: {spec.name} ({spec.describe()})" for spec in self.create]
        lines += [
            f"  differs, left as it is: {drift.name} ({'; '.join(drift.differences)})"
            for drift in self.drift
        ]
        if self.matching:
            count = len(self.matching)
            lines.append(f"  as the file says: {count} topic{'s' if count != 1 else ''}")
        if self.unlisted:
            lines.append(f"  not in the file, left alone: {', '.join(self.unlisted)}")
        return lines

    def summary(self, *, applied: bool = False) -> str:
        made = f"{len(self.create)} {'created' if applied else 'to create'}"
        return (
            f"{made}, {len(self.drift)} differing, {len(self.matching)} as the file says, "
            f"replication factor {self.replication_factor} ({self.brokers} "
            f"broker{'s' if self.brokers != 1 else ''})"
        )


def differences(spec: TopicSpec, topic: BrokerTopic) -> tuple[str, ...]:
    """How the broker's topic differs from the file; a setting the broker did not report is
    not a difference."""
    found: list[str] = []
    if topic.partitions != spec.partitions:
        found.append(f"partitions {topic.partitions} on the broker, {spec.partitions} in the file")
    for key, wanted in spec.configs().items():
        actual = topic.configs.get(key)
        if actual is not None and actual != wanted:
            found.append(f"{key} {actual} on the broker, {wanted} in the file")
    return tuple(found)


def plan(wanted: TopicsFile, existing: Mapping[str, BrokerTopic], brokers: int) -> TopicPlan:
    create: list[TopicSpec] = []
    drift: list[Drift] = []
    matching: list[str] = []
    for spec in wanted.topics:
        topic = existing.get(spec.name)
        if topic is None:
            create.append(spec)
            continue
        found = differences(spec, topic)
        if found:
            drift.append(Drift(spec.name, found))
        else:
            matching.append(spec.name)
    unlisted = sorted(
        name for name in existing if name not in wanted.names and not name.startswith("_")
    )
    return TopicPlan(
        create=tuple(create),
        drift=tuple(drift),
        matching=tuple(matching),
        unlisted=tuple(unlisted),
        brokers=brokers,
        replication_factor=max(1, min(wanted.replication_factor, brokers)),
    )


async def make_plan(admin: TopicAdmin, wanted: TopicsFile) -> TopicPlan:
    brokers = await admin.brokers()
    existing = await admin.topics(with_configs=wanted.names)
    return plan(wanted, existing, brokers)


async def apply(admin: TopicAdmin, wanted: TopicsFile) -> TopicPlan:
    """Create what the broker lacks; the plan says what that was."""
    current = await make_plan(admin, wanted)
    if current.create:
        await admin.create(current.create, current.replication_factor)
    return current


class KafkaTopicAdmin:
    """The broker through aiokafka's admin client, connected as every other Kafka client of
    the deployable is (``KafkaClientConfig``)."""

    def __init__(self, config: KafkaClientConfig) -> None:
        self._client = AIOKafkaAdminClient(
            **config.aiokafka_kwargs(), client_id=CLIENT_ID, request_timeout_ms=REQUEST_TIMEOUT_MS
        )

    async def __aenter__(self) -> Self:
        await self._client.start()
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        await self._client.close()

    async def brokers(self) -> int:
        cluster: dict[str, Any] = await self._client.describe_cluster()
        return len(cluster.get("brokers") or ())

    async def topics(self, with_configs: Collection[str]) -> dict[str, BrokerTopic]:
        described: list[dict[str, Any]] = await self._client.describe_topics()
        partitions = {
            str(topic["topic"]): len(topic["partitions"])
            for topic in described
            if not topic.get("error_code") and not topic.get("is_internal")
        }
        configs = await self._configs([name for name in with_configs if name in partitions])
        return {
            name: BrokerTopic(name, count, configs.get(name, {}))
            for name, count in partitions.items()
        }

    async def _configs(self, names: Sequence[str]) -> dict[str, dict[str, str]]:
        if not names:
            return {}
        resources = [
            ConfigResource(
                ConfigResourceType.TOPIC, name, configs=dict.fromkeys((RETENTION, CLEANUP))
            )
            for name in names
        ]
        found: dict[str, dict[str, str]] = {}
        for response in await self._client.describe_configs(resources):
            for resource in response.to_object()["resources"]:
                if resource["error_code"]:
                    continue
                found[str(resource["resource_name"])] = {
                    str(entry["config_names"]): str(entry["config_value"])
                    for entry in resource["config_entries"]
                    if entry["config_value"] is not None
                }
        return found

    async def create(self, topics: Sequence[TopicSpec], replication_factor: int) -> None:
        response = await self._client.create_topics(
            [
                NewTopic(
                    name=spec.name,
                    num_partitions=spec.partitions,
                    replication_factor=replication_factor,
                    topic_configs=spec.configs(),
                )
                for spec in topics
            ],
            timeout_ms=REQUEST_TIMEOUT_MS,
        )
        refused = [
            f"{error[0]}: {for_code(error[1]).__name__}"
            + (f" ({error[2]})" if len(error) > 2 and error[2] else "")
            for error in response.topic_errors
            if error[1] not in (0, TOPIC_ALREADY_EXISTS)
        ]
        if refused:
            raise TopicsError(f"the broker refused to create {'; '.join(refused)}")
