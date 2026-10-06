"""``topics.toml`` lists every contract topic and every dead-letter topic of a consumer group the
worker hosts, and nothing else."""

import re
from pathlib import Path

from cw_mvp.testing import mvp_settings
from cw_mvp.topics import TOPICS_FILE, load
from cw_mvp.worker import build_registry
from py_common.settings import Settings

REPO = Path(__file__).resolve().parents[4]
SCHEMAS = REPO / "packages" / "contracts" / "events" / "schemas"
VERSIONED = re.compile(r"(?P<topic>.+)\.v\d+\.json")
NOT_A_TOPIC = frozenset({"envelope"})


def contract_topics() -> set[str]:
    """``<topic>.v<major>.json`` names a topic; the envelope is every message's frame."""
    topics: set[str] = set()
    for path in SCHEMAS.glob("*.json"):
        match = VERSIONED.fullmatch(path.name)
        assert match is not None, f"{path.name} is not <topic>.v<major>.json"
        topics.add(match["topic"])
    return topics - NOT_A_TOPIC


async def no_tables(settings: Settings, table: str) -> bool:
    """A worker that finds no outbox or idempotency table still hosts every consumer."""
    return False


FLAGGED_CONSUMERS = {"rulebook": {"rulebook_candidate_intake_enabled": True}}
"""The consumer groups the worker hosts only behind a flag of their own, turned on."""


async def dead_letter_topics() -> set[str]:
    """``<topic>.<group>.dlq`` of every consumer group the worker hosts with Kafka on, and every
    flag that adds a group on."""
    hosted = await build_registry(
        mvp_settings(worker_kafka_enabled=True),
        probe=no_tables,
        service_overrides=FLAGGED_CONSUMERS,
    )
    consumers = [consumer for entry in hosted.hosted for consumer in entry.components.consumers]
    assert consumers, "the worker hosts no consumer group"
    return {topic for consumer in consumers for topic in consumer.dead_letter_topics()}


def test_the_file_is_beside_the_package_and_parses() -> None:
    assert TOPICS_FILE == REPO / "composition" / "mvp" / "topics.toml"
    assert load().replication_factor == 3


def test_every_contract_topic_is_in_the_file() -> None:
    topics = contract_topics()
    assert {"profile.updated", "rule.published", "applicability.decided"} <= topics
    missing = sorted(topics - load().names)
    assert missing == [], f"add these contract topics to {TOPICS_FILE.name}: {missing}"


async def test_every_consumer_groups_dead_letter_topic_is_in_the_file() -> None:
    dead_letters = await dead_letter_topics()
    assert "profile.updated.applicability-engine.profiles.dlq" in dead_letters
    assert "rule.candidate.created.rulebook.rule-candidates.dlq" in dead_letters
    missing = sorted(dead_letters - load().names)
    assert missing == [], f"add these dead-letter topics to {TOPICS_FILE.name}: {missing}"


async def test_the_file_lists_nothing_else() -> None:
    stale = sorted(load().names - contract_topics() - await dead_letter_topics())
    assert stale == [], f"no contract or consumer group has these topics any more: {stale}"


def test_dead_letters_and_rule_events_keep_one_partition_for_a_month() -> None:
    by_name = {topic.name: topic for topic in load().topics}
    for name, topic in by_name.items():
        if name.endswith(".dlq") or name.startswith("rule."):
            assert (topic.partitions, topic.retention_days) == (1, 30), name
        assert topic.cleanup_policy == "delete", name
