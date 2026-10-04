"""CW_RULEBOOK_SEED_ON_START: the memory store starts with the seed calendar's drafts, written the
way ``rulebook-seed`` writes them into Postgres, and only in local and test."""

from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

import ontology as ontology_package
from domain_kernel.ids import RuleId
from domain_kernel.predicates import specification_to_mapping
from domain_kernel.status import RuleVersionStatus
from rulebook.application.seed_loader import load_calendar
from rulebook.domain.seed import SeedCalendar, SeedStatus
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.main import build_app, seed_memory_store
from rulebook.testing import rulebook_settings

BASE = "/v1/rulebook"


@pytest.fixture(scope="module")
def calendar() -> SeedCalendar:
    return load_calendar(ontology_package.load())


def _edited(calendar: SeedCalendar, rule_key: str, **changes: Any) -> SeedCalendar:
    rules = tuple(
        replace(rule, **changes) if rule.rule_key == rule_key else rule for rule in calendar.rules
    )
    return replace(calendar, rules=rules)


def _versions(store: MemoryKnowledgeStore, rule_key: str) -> list[tuple[int, str, str]]:
    with store() as uow:
        rule_id = uow.rules.rule_id(rule_key)
        assert rule_id is not None
        return [
            (record.version, record.status.value, record.title)
            for record in uow.rule_versions.of_rule(RuleId(rule_id))
        ]


def test_every_seed_rule_becomes_a_draft_that_needs_review(calendar: SeedCalendar) -> None:
    store = MemoryKnowledgeStore()
    outcome = store.apply_seed(calendar)
    assert outcome.created_rules == calendar.keys
    assert outcome.created_versions == tuple(f"{key}@1" for key in calendar.keys)
    assert outcome.summary == "13 new rules, 13 new versions, 0 drafts updated, 0 unchanged"
    with store() as uow:
        assert [rule.rule_key for rule in uow.rules.list_rules()] == sorted(calendar.keys)
        for seeded in calendar.rules:
            rule_id = uow.rules.rule_id(seeded.rule_key)
            assert rule_id is not None
            (record,) = uow.rule_versions.of_rule(RuleId(rule_id))
            assert (record.version, record.status) == (1, RuleVersionStatus.DRAFT)
            assert record.seed_status is SeedStatus.NEEDS_REVIEW
            assert (record.title, record.summary) == (seeded.title, seeded.summary)
            assert (record.regulator, record.level) == (seeded.regulator, seeded.level)
            assert record.specification == specification_to_mapping(seeded.specification)
            assert record.obligation_template == seeded.obligation_template.to_mapping()
            expected = None if seeded.recurrence is None else seeded.recurrence.to_mapping()
            assert record.recurrence == expected
            assert record.effective_from == seeded.effective_from
            assert record.effective_to is None
            assert record.source == seeded.source.to_mapping()
            assert record.todo == seeded.todo
            assert (record.published_at, record.submitted_at, record.high_impact) == (
                None,
                None,
                False,
            )


def test_a_second_run_changes_nothing(calendar: SeedCalendar) -> None:
    store = MemoryKnowledgeStore()
    store.apply_seed(calendar)
    again = store.apply_seed(calendar)
    assert (again.created_rules, again.created_versions, again.updated_drafts) == ((), (), ())
    assert again.unchanged == calendar.keys


def test_an_edited_rule_updates_its_draft_in_place(calendar: SeedCalendar) -> None:
    store = MemoryKnowledgeStore()
    store.apply_seed(calendar)
    key = calendar.keys[0]
    outcome = store.apply_seed(_edited(calendar, key, title="Example title, edited"))
    assert outcome.updated_drafts == (f"{key}@1",)
    assert _versions(store, key) == [(1, "draft", "Example title, edited")]
    with store() as uow:
        listed = {rule.rule_key: rule.title for rule in uow.rules.list_rules()}
    assert listed[key] == "Example title, edited"


def test_a_version_past_draft_is_kept_and_a_changed_rule_gets_a_new_draft(
    calendar: SeedCalendar,
) -> None:
    store = MemoryKnowledgeStore()
    store.apply_seed(calendar)
    key = calendar.keys[1]
    with store() as uow:
        rule_id = uow.rules.rule_id(key)
        assert rule_id is not None
        (draft,) = uow.rule_versions.of_rule(RuleId(rule_id))
        uow.rule_versions.save_lifecycle(replace(draft, status=RuleVersionStatus.IN_REVIEW))
    unchanged = store.apply_seed(calendar)
    assert key in unchanged.unchanged
    title = calendar.get(key).title
    assert _versions(store, key) == [(1, "in_review", title)]

    changed = store.apply_seed(_edited(calendar, key, effective_from=date(2000, 1, 1)))
    assert changed.created_versions == (f"{key}@2",)
    assert _versions(store, key) == [(1, "in_review", title), (2, "draft", title)]


def test_a_reviewed_seed_status_alone_is_no_change(calendar: SeedCalendar) -> None:
    store = MemoryKnowledgeStore()
    store.apply_seed(calendar)
    key = calendar.keys[2]
    with store() as uow:
        rule_id = uow.rules.rule_id(key)
        assert rule_id is not None
        (draft,) = uow.rule_versions.of_rule(RuleId(rule_id))
        uow.rule_versions.save_lifecycle(
            replace(draft, status=RuleVersionStatus.IN_REVIEW, seed_status=SeedStatus.REVIEWED)
        )
    assert key in store.apply_seed(calendar).unchanged
    assert [version for version, _, _ in _versions(store, key)] == [1]


def test_the_composition_root_loads_the_calendar_into_the_store(calendar: SeedCalendar) -> None:
    store = MemoryKnowledgeStore()
    outcome = seed_memory_store(store)
    assert outcome.created_rules == calendar.keys


def test_the_app_built_with_seed_on_start_lists_the_drafts(calendar: SeedCalendar) -> None:
    app = build_app(rulebook_settings(rulebook_seed_on_start=True))
    with TestClient(app) as client:
        rules = client.get(f"{BASE}/rules")
        assert rules.status_code == 200
        assert [rule["rule_key"] for rule in rules.json()] == sorted(calendar.keys)
        key = calendar.keys[0]
        versions = client.get(f"{BASE}/rules/{key}/versions").json()
        assert [(v["version"], v["status"], v["seed_status"]) for v in versions] == [
            (1, "draft", "needs_review")
        ]
        assert versions[0]["todo"] == list(calendar.get(key).todo)
        detail = client.get(f"{BASE}/rule-versions/{versions[0]['rule_version_id']}")
        assert detail.status_code == 200
        assert detail.json()["citations"] == []
        # A draft is not in force on any date: only the publish flow puts a version there.
        in_force = client.get(f"{BASE}/rule-versions", params={"as_of": "2026-10-01"})
        assert in_force.json() == []


def test_the_app_starts_empty_without_it() -> None:
    with TestClient(build_app(rulebook_settings())) as client:
        assert client.get(f"{BASE}/rules").json() == []
