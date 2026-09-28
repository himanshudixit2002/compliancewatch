"""The CHECK constraints in the models carry the kernel's vocabulary and rules, value for value.

No database: this reads ``Base.metadata``. Alembic autogenerate does not compare CHECK bodies,
so this test and the inspector-based integration test are what keep the models, the migration
and the kernel in step.
"""

import re

from sqlalchemy import CheckConstraint

from domain_kernel.knowledge import RULE_VERSION_KIND, RULE_VERSION_ONLY, EntityType, RelationKind
from rulebook.infrastructure.models import (
    ENTITY_TYPES,
    RELATION_KINDS,
    RULE_VERSION_ONLY_RELATIONS,
    RULE_VERSION_TARGET,
    TARGET_KINDS,
    Base,
)

QUOTED = re.compile(r"'([a-z_]+)'")


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


def test_every_check_is_named() -> None:
    for table in ("canonical_entity", "clause_entity", "rule_relation"):
        for constraint in Base.metadata.tables[table].constraints:
            if isinstance(constraint, CheckConstraint):
                assert isinstance(constraint.name, str)
                assert constraint.name.startswith(f"ck_{table}_")
