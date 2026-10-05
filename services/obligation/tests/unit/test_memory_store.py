"""The memory store's cached rule versions and applied decisions behave as the Postgres ones:
a merge never moves a version back, a unit's writes land only when it exits cleanly, and an
older decision never replaces a later one."""

from datetime import UTC, datetime, timedelta

import pytest

from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId
from domain_kernel.status import RuleVersionStatus
from obligation.domain.rule_versions import AppliedDecision
from obligation.infrastructure.memory import MemoryStore
from obligation.testing import NOW, ref_of, rule

MADE = datetime(2026, 10, 1, tzinfo=UTC)


def test_cached_versions_merge_and_commit_with_the_unit() -> None:
    store, the_rule, tenant = MemoryStore(), rule(), TenantId.new()
    refs = store.rule_version_refs()
    assert refs.get(the_rule.rule_version_id) is None
    withdrawn = refs.merge(ref_of(the_rule, status=RuleVersionStatus.WITHDRAWN))
    assert refs.get(the_rule.rule_version_id, lock=True) == withdrawn
    later = ref_of(the_rule, title="Retitled", fetched_at=NOW + timedelta(minutes=1))
    with store(tenant) as uow:
        merged = uow.rule_versions.merge(later)
    assert (merged.status, merged.title) == (RuleVersionStatus.WITHDRAWN, "Retitled")
    assert store.rule_versions[the_rule.rule_version_id] == merged

    def failing() -> None:
        with store(tenant) as uow:
            uow.rule_versions.merge(ref_of(rule()))
            raise RuntimeError("rolled back")

    with pytest.raises(RuntimeError):
        failing()
    assert len(store.rule_versions) == 1, "a unit that fails writes nothing"


def test_an_older_decision_never_replaces_a_later_one() -> None:
    store, tenant = MemoryStore(), TenantId.new()
    business, version = BusinessId.new(), RuleVersionId.new()
    later = AppliedDecision(tenant, business, version, DecisionId.new(), False, MADE)
    older = AppliedDecision(
        tenant, business, version, DecisionId.new(), True, MADE - timedelta(hours=1)
    )
    with store(tenant) as uow:
        assert uow.decisions.record(later)
        assert not uow.decisions.record(older)
        assert uow.decisions.applying() == []
    with store(tenant) as uow:
        newest = AppliedDecision(tenant, business, version, DecisionId.new(), True, MADE)
        assert uow.decisions.record(newest)
        assert uow.decisions.applying() == [newest]
    with store(TenantId.new()) as uow:
        assert uow.decisions.applying() == [], "another tenant's"
        with pytest.raises(ValueError, match="another tenant"):
            uow.decisions.record(newest)
