"""The CHECK constraints in the models carry the kernel's vocabulary and rules, value for value.

No database: this reads ``Base.metadata``. Alembic autogenerate does not compare CHECK bodies,
so this test and the inspector-based integration test are what keep the models, the migration
and the kernel in step.
"""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

from sqlalchemy import CheckConstraint

from domain_kernel.documents import PARSER_VERSION_PATTERN, DocumentType
from domain_kernel.knowledge import RULE_VERSION_KIND, RULE_VERSION_ONLY, EntityType, RelationKind
from domain_kernel.status import RULE_VERSION_TRANSITIONS, RuleVersionStatus
from rulebook.domain.documents import CLAUSE_REF_PATTERN
from rulebook.domain.publication import DecisionAction
from rulebook.infrastructure.models import (
    DECISION_ACTIONS,
    DOCUMENT_TYPES,
    ENTITY_TYPES,
    MENTION_METHODS,
    RELATION_KINDS,
    RULE_VERSION_ONLY_RELATIONS,
    RULE_VERSION_STATUSES,
    RULE_VERSION_TARGET,
    TARGET_KINDS,
    Base,
)

QUOTED = re.compile(r"'([a-z_]+)'")
PAIR = re.compile(r"\('([a-z_]+)', '([a-z_]+)'\)")
PUBLISH_FLOW = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "20260929_0007_publish_flow.py"
)


def _publish_flow_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("publish_flow_migration", PUBLISH_FLOW)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check(table: str, name: str) -> str:
    checks = {
        constraint.name: constraint
        for constraint in Base.metadata.tables[table].constraints
        if isinstance(constraint, CheckConstraint)
    }
    return str(checks[name].sqltext)


def test_module_constants_are_the_kernel_enums() -> None:
    assert tuple(kind.value for kind in EntityType) == ENTITY_TYPES
    assert tuple(kind.value for kind in RelationKind) == RELATION_KINDS
    assert RULE_VERSION_TARGET == RULE_VERSION_KIND
    assert (RULE_VERSION_KIND, *ENTITY_TYPES) == TARGET_KINDS
    assert set(RULE_VERSION_ONLY_RELATIONS) == {kind.value for kind in RULE_VERSION_ONLY}
    assert RULE_VERSION_ONLY_RELATIONS == (
        "supersedes",
        "extends_deadline",
        "corrects",
        "withdraws",
    )
    assert len(TARGET_KINDS) == 11


def test_entity_type_check_lists_every_entity_type() -> None:
    body = _check("canonical_entity", "ck_canonical_entity_type")
    assert body.startswith("type IN (")
    assert QUOTED.findall(body) == [kind.value for kind in EntityType]


def test_relation_and_to_kind_checks_list_the_kernel_vocabulary() -> None:
    relation = _check("rule_relation", "ck_rule_relation_relation")
    assert relation.startswith("relation IN (")
    assert QUOTED.findall(relation) == [kind.value for kind in RelationKind]

    to_kind = _check("rule_relation", "ck_rule_relation_to_kind")
    assert to_kind.startswith("to_kind IN (")
    assert QUOTED.findall(to_kind) == [RULE_VERSION_KIND, *(kind.value for kind in EntityType)]


def test_pairing_target_and_self_checks_repeat_the_kernel_rules() -> None:
    pairing = _check("rule_relation", "ck_rule_relation_pairing")
    assert pairing == (
        "relation NOT IN ('supersedes', 'extends_deadline', 'corrects', 'withdraws') "
        "OR to_kind = 'rule_version'"
    )
    assert set(QUOTED.findall(pairing)) == {
        *(kind.value for kind in RULE_VERSION_ONLY),
        RULE_VERSION_KIND,
    }

    target = _check("rule_relation", "ck_rule_relation_target_entity")
    assert target == "(to_kind = 'rule_version') = (to_entity_id IS NULL)"

    not_self = _check("rule_relation", "ck_rule_relation_not_self")
    assert not_self == ("NOT (to_kind = 'rule_version' AND to_ref = from_rule_version_id::text)")

    target_version = _check("rule_relation", "ck_rule_relation_target_version")
    assert target_version == (
        "((to_kind = 'rule_version') = (to_rule_version_id IS NOT NULL))"
        " AND (to_rule_version_id IS NULL OR to_ref = to_rule_version_id::text)"
    )


def test_document_and_clause_checks_follow_the_kernel() -> None:
    assert tuple(kind.value for kind in DocumentType) == DOCUMENT_TYPES
    doc_type = _check("document", "ck_document_doc_type")
    assert QUOTED.findall(doc_type) == list(DOCUMENT_TYPES)
    assert PARSER_VERSION_PATTERN in _check("document", "ck_document_parser_version")
    assert CLAUSE_REF_PATTERN in _check("clause", "ck_clause_clause_ref")
    assert QUOTED.findall(_check("clause_entity", "ck_clause_entity_method")) == list(
        MENTION_METHODS
    )


def test_citation_verification_needs_a_passing_score() -> None:
    verified = _check("citation", "ck_citation_verified")
    assert "verified_at IS NOT NULL" in verified
    assert "match_score >= 0.85" in verified


def test_every_check_is_named() -> None:
    for table in Base.metadata.tables:
        for constraint in Base.metadata.tables[table].constraints:
            if isinstance(constraint, CheckConstraint):
                assert isinstance(constraint.name, str)
                assert constraint.name.startswith(f"ck_{table}_")


def test_the_rule_version_guard_allows_exactly_the_kernel_transitions() -> None:
    guard: str = _publish_flow_migration().GUARD
    literal_pairs = set(PAIR.findall(guard))
    kernel_pairs = {
        (state.value, successor.value)
        for state in RuleVersionStatus
        for successor in RULE_VERSION_TRANSITIONS.successors(state)
    }
    assert literal_pairs == kernel_pairs
    assert "OLD.status IN ('published', 'superseded', 'withdrawn')" in guard


def test_decision_actions_and_statuses_follow_the_domain() -> None:
    migration = _publish_flow_migration()
    assert tuple(action.value for action in DecisionAction) == DECISION_ACTIONS
    assert migration.DECISION_ACTIONS == DECISION_ACTIONS
    assert migration.RULE_VERSION_STATUSES == RULE_VERSION_STATUSES
    assert QUOTED.findall(_check("rule_version_decision", "ck_rule_version_decision_action")) == (
        list(DECISION_ACTIONS)
    )
    for column in ("from_status", "to_status"):
        body = _check("rule_version_decision", f"ck_rule_version_decision_{column}")
        assert QUOTED.findall(body) == [status.value for status in RuleVersionStatus]
    assert _check("rule_version_decision", "ck_rule_version_decision_actor") == (
        "actor_id IS NOT NULL OR caused_by_rule_version_id IS NOT NULL"
    )
