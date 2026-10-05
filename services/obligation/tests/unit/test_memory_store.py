"""The memory store's cached rule versions, applied decisions, comments and audit entries behave
as the Postgres ones: a merge never moves a version back, a unit's writes land only when it exits
cleanly, an older decision never replaces a later one, and a tenant reads and writes only its own
comments."""

from datetime import UTC, datetime, timedelta

import pytest

from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.ids import BusinessId, DecisionId, ObligationId, RuleVersionId, TenantId
from domain_kernel.status import RuleVersionStatus
from obligation.domain.comments import CommentId, ObligationComment
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


def comment(tenant: TenantId, obligation: ObligationId, at: datetime) -> ObligationComment:
    return ObligationComment(
        id=CommentId.new(),
        tenant_id=tenant,
        obligation_id=obligation,
        author_id=None,
        author_label="system:obligation",
        body="Example comment (synthetic)",
        created_at=at,
    )


def test_comments_and_audit_entries_land_with_the_unit_and_stay_with_their_tenant() -> None:
    store, tenant, other = MemoryStore(), TenantId.new(), TenantId.new()
    obligation = ObligationId.new()
    later, earlier = (
        comment(tenant, obligation, MADE),
        comment(tenant, obligation, MADE - timedelta(hours=1)),
    )
    entry = AuditEntry(
        action="obligation.comment",
        tenant_id=tenant,
        subject_type="obligation",
        subject_id=str(obligation),
        actor=AuditActor.system("obligation"),
        after={"comment_id": str(later.id)},
    )
    with store(tenant) as uow:
        uow.comments.add(later)
        uow.comments.add(earlier)
        uow.audit.write(entry)
        assert uow.comments.for_obligation(obligation) == [earlier, later]
        assert store.comments == [], "nothing lands before the unit ends"
        assert store.audit == []
        with pytest.raises(ValueError, match="duplicate"):
            uow.comments.add(later)
    assert store.comments == [later, earlier]
    assert store.audit == [entry]

    def failing() -> None:
        with store(tenant) as uow:
            uow.comments.add(comment(tenant, obligation, MADE))
            uow.audit.write(
                AuditEntry(
                    action="obligation.comment",
                    tenant_id=tenant,
                    subject_type="obligation",
                    subject_id=str(obligation),
                    actor=AuditActor.system("obligation"),
                )
            )
            raise RuntimeError("rolled back")

    with pytest.raises(RuntimeError):
        failing()
    assert (len(store.comments), len(store.audit)) == (2, 1), "a unit that fails writes nothing"
    with store(other) as uow:
        assert uow.comments.for_obligation(obligation) == [], "another tenant's"
        with pytest.raises(ValueError, match="another tenant"):
            uow.comments.add(comment(tenant, obligation, MADE))
        with pytest.raises(ValueError, match="another tenant"):
            uow.audit.write(entry)
