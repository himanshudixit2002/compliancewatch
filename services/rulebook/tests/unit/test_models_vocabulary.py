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
from rulebook.domain.intake import CandidateOutcome, RuleCandidateStatus, RuleRejectReason
from rulebook.domain.publication import DecisionAction
from rulebook.domain.review_tasks import (
    UNDECIDED,
    ReviewDecision,
    ReviewTaskKind,
    ReviewTaskStatus,
)
from rulebook.infrastructure.models import (
    CANDIDATE_OUTCOMES,
    DECISION_ACTIONS,
    DOCUMENT_TYPES,
    ENTITY_TYPES,
    MENTION_METHODS,
    RELATION_KINDS,
    REVIEW_DECISIONS,
    REVIEW_TASK_KINDS,
    REVIEW_TASK_STATUSES,
    RULE_CANDIDATE_STATUSES,
    RULE_REJECT_REASONS,
    RULE_VERSION_ONLY_RELATIONS,
    RULE_VERSION_STATUSES,
    RULE_VERSION_TARGET,
    TARGET_KINDS,
    UNDECIDED_TASK,
    Base,
)

QUOTED = re.compile(r"'([a-z_]+)'")
PAIR = re.compile(r"\('([a-z_]+)', '([a-z_]+)'\)")
VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"
PUBLISH_FLOW = VERSIONS / "20260929_0007_publish_flow.py"
REVIEW_TASKS = VERSIONS / "20261006_0009_review_tasks.py"
RULE_CANDIDATES = VERSIONS / "20261006_0010_rule_candidates.py"


def _migration(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _publish_flow_migration() -> ModuleType:
    return _migration(PUBLISH_FLOW)


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


def test_the_insert_guard_admits_only_unpublished_drafts() -> None:
    guard: str = _publish_flow_migration().INSERT_GUARD
    assert "NEW.status IS DISTINCT FROM 'draft' OR NEW.published_at IS NOT NULL" in guard
    assert not PAIR.findall(guard)


def test_decision_actions_and_statuses_follow_the_domain() -> None:
    migration = _publish_flow_migration()
    review_tasks = _migration(REVIEW_TASKS)
    assert tuple(action.value for action in DecisionAction) == DECISION_ACTIONS
    assert migration.DECISION_ACTIONS == review_tasks.ACTIONS_BEFORE
    assert review_tasks.ACTIONS_AFTER == DECISION_ACTIONS
    assert set(DECISION_ACTIONS) - set(migration.DECISION_ACTIONS) == {"edited"}
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


def test_review_task_checks_follow_the_domain() -> None:
    migration = _migration(REVIEW_TASKS)
    candidates = _migration(RULE_CANDIDATES)
    assert migration.KINDS == candidates.KINDS_BEFORE == ("seed",)
    assert tuple(kind.value for kind in ReviewTaskKind) == REVIEW_TASK_KINDS
    assert candidates.KINDS_AFTER == REVIEW_TASK_KINDS
    assert (
        tuple(status.value for status in ReviewTaskStatus)
        == REVIEW_TASK_STATUSES
        == migration.STATUSES
    )
    assert (
        tuple(decision.value for decision in ReviewDecision)
        == REVIEW_DECISIONS
        == migration.DECISIONS
    )
    assert QUOTED.findall(_check("review_task", "ck_review_task_kind")) == list(REVIEW_TASK_KINDS)
    assert QUOTED.findall(_check("review_task", "ck_review_task_status")) == list(
        REVIEW_TASK_STATUSES
    )
    assert QUOTED.findall(_check("review_task", "ck_review_task_decision")) == list(
        REVIEW_DECISIONS
    )
    assert set(QUOTED.findall(UNDECIDED_TASK)) == {status.value for status in UNDECIDED}
    assert migration.UNDECIDED == candidates.UNDECIDED == UNDECIDED_TASK
    state = _check("review_task", "ck_review_task_state")
    assert set(QUOTED.findall(state)) == set(REVIEW_TASK_STATUSES)
    subject = _check("review_task", "ck_review_task_subject")
    assert set(QUOTED.findall(subject)) == set(REVIEW_TASK_KINDS)
    assert "kind = 'seed' AND rule_version_id IS NOT NULL AND candidate_id IS NULL" in subject


def test_the_review_task_guard_keeps_decided_tasks_and_identities() -> None:
    guard: str = _migration(REVIEW_TASKS).GUARD
    assert "OLD.status = 'decided'" in guard
    assert "TG_OP = 'DELETE'" in guard
    assert "NEW.rule_version_id, NEW.kind, NEW.regulator, NEW.opened_at" in guard
    candidates = _migration(RULE_CANDIDATES)
    assert candidates.GUARD_BEFORE.strip() == guard.strip().replace(
        "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION"
    ), "the downgrade restores 0009's guard as it was"
    after: str = candidates.GUARD_AFTER
    assert "NEW.id, NEW.kind, NEW.candidate_id, NEW.regulator, NEW.opened_at" in after
    assert "OLD.rule_version_id IS NOT NULL" in after, "a version is taken once, never changed"
    assert "OLD.status = 'decided'" in after
    assert "TG_OP = 'DELETE'" in after


def test_rule_candidate_checks_follow_the_domain() -> None:
    migration = _migration(RULE_CANDIDATES)
    assert tuple(outcome.value for outcome in CandidateOutcome) == CANDIDATE_OUTCOMES
    assert migration.OUTCOMES == CANDIDATE_OUTCOMES
    assert tuple(status.value for status in RuleCandidateStatus) == RULE_CANDIDATE_STATUSES
    assert migration.STATUSES == RULE_CANDIDATE_STATUSES
    assert tuple(reason.value for reason in RuleRejectReason) == RULE_REJECT_REASONS
    assert migration.REJECT_REASONS == RULE_REJECT_REASONS
    assert QUOTED.findall(_check("rule_candidate", "ck_rule_candidate_outcome")) == list(
        CANDIDATE_OUTCOMES
    )
    assert QUOTED.findall(_check("rule_candidate", "ck_rule_candidate_status")) == list(
        RULE_CANDIDATE_STATUSES
    )
    assert QUOTED.findall(_check("rule_candidate", "ck_rule_candidate_reject_reason")) == list(
        RULE_REJECT_REASONS
    )
    state = _check("rule_candidate", "ck_rule_candidate_state")
    assert set(QUOTED.findall(state)) == set(RULE_CANDIDATE_STATUSES)
