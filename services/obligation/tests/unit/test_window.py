"""The rolling window and ``obligation-sweep`` on the memory store: the period that entered the
window is made once, a one-off rule and a decision that no longer applies are left alone, the
guard keeps a withdrawn or superseded version from making what it no longer governs, a failing
tenant is reported, and the command refuses what it must not do."""

import io
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest

from domain_kernel.ids import BusinessId, DecisionId, TenantId
from domain_kernel.predicates import Applicability
from domain_kernel.rules import RuleVersionSnapshot
from domain_kernel.status import RuleVersionStatus
from obligation import sweep
from obligation.application.decisions import ApplyDecision, Decision
from obligation.application.window import RollWindow
from obligation.domain.rule_versions import Refusal
from obligation.infrastructure.memory import MemoryStore
from obligation.settings import ObligationSettings
from obligation.testing import FakeRuleVersionReader, rule

DECIDED_AT = datetime(2026, 10, 1, 4, 0, tzinfo=UTC)
NEXT_MONTH = datetime(2026, 11, 2, 4, 0, tzinfo=UTC)


def decided(
    store: MemoryStore,
    reader: FakeRuleVersionReader,
    the_rule: RuleVersionSnapshot,
    tenant: TenantId,
    business: BusinessId,
    result: Applicability = Applicability.APPLIES,
    at: datetime = DECIDED_AT,
    profile_version: int | None = 7,
) -> None:
    ApplyDecision(reader, clock=lambda: at).run(
        Decision(
            tenant_id=tenant,
            decision_id=DecisionId.new(),
            business_id=business,
            rule_version_id=the_rule.rule_version_id,
            result=result,
            needs_review=False,
            decided_at=at,
            profile_version=profile_version,
        ),
        store,
    )


def labels(store: MemoryStore, tenant: TenantId) -> list[str]:
    return sorted(o.period_label or "one-off" for o in store.of_tenant(tenant))


def test_the_window_makes_the_period_that_entered_it_once() -> None:
    store, the_rule, one_off = MemoryStore(), rule(), rule(recurrence=None, due_in_days=10)
    reader = FakeRuleVersionReader([the_rule, one_off])
    tenant, other = TenantId.new(), TenantId.new()
    business, flipped = BusinessId.new(), BusinessId.new()
    decided(store, reader, the_rule, tenant, business)
    decided(store, reader, one_off, tenant, business)
    decided(store, reader, the_rule, other, flipped)
    decided(store, reader, the_rule, other, flipped, Applicability.NOT_APPLICABLE)
    assert labels(store, tenant) == ["2026-10", "2026-11", "one-off"]

    roll = RollWindow(store, store, reader, clock=lambda: NEXT_MONTH)
    rolled = roll.run()
    assert (rolled.tenants, len(rolled.created), rolled.refused, rolled.failed) == (2, 1, (), ())
    assert labels(store, tenant) == ["2026-10", "2026-11", "2026-12", "one-off"]
    assert labels(store, other) == ["2026-10", "2026-11"], "no longer applies: nothing new"
    (made,) = [store.obligations[o] for o in rolled.created]
    assert made.business_id == business
    assert made.profile_version == 7, "the profile version of the decision it rolls"
    assert roll.run().created == (), "a second run makes nothing"
    assert roll.run(only={other}).tenants == 1


def test_the_window_asks_the_guard() -> None:
    store, the_rule, cut_rule = MemoryStore(), rule(), rule()
    reader = FakeRuleVersionReader([the_rule, cut_rule])
    tenant = TenantId.new()
    decided(store, reader, the_rule, tenant, BusinessId.new())
    decided(store, reader, cut_rule, tenant, BusinessId.new())
    reader.end(the_rule.rule_version_id, RuleVersionStatus.WITHDRAWN)
    reader.end(cut_rule.rule_version_id, RuleVersionStatus.SUPERSEDED, date(2026, 12, 1))
    for ref in reader.refs.values():
        store.rule_versions[ref.rule_version_id] = ref

    rolled = RollWindow(store, store, reader, clock=lambda: NEXT_MONTH).run()
    assert rolled.created == ()
    assert dict(rolled.refused) == {Refusal.RULE_SUPERSEDED: 1}, "December; withdrawn is quiet"

    later = RollWindow(store, store, reader, clock=lambda: datetime(2026, 12, 2, tzinfo=UTC))
    assert later.run().refused == (), "no longer in force: nothing to roll, nothing to report"


def test_a_failing_tenant_is_reported_and_the_rest_roll() -> None:
    store, the_rule = MemoryStore(), rule()
    reader = FakeRuleVersionReader([the_rule])
    tenant = TenantId.new()
    decided(store, reader, the_rule, tenant, BusinessId.new())
    reader.down = True
    failures: list[TenantId] = []
    rolled = RollWindow(
        store,
        store,
        reader,
        clock=lambda: NEXT_MONTH,
        on_failure=lambda failed, exc: failures.append(failed),
    ).run()
    assert (rolled.failed, failures) == ((tenant,), [tenant])
    with pytest.raises(Exception, match="unreachable"):
        RollWindow(store, store, reader, clock=lambda: NEXT_MONTH).run()


def test_run_once_sweeps_reminders_and_rolls_the_window_as_of_now() -> None:
    store, the_rule = MemoryStore(), rule()
    reader = FakeRuleVersionReader([the_rule])
    tenant, other = TenantId.new(), TenantId.new()
    decided(store, reader, the_rule, tenant, BusinessId.new())
    decided(store, reader, the_rule, other, BusinessId.new())
    now = datetime(2026, 11, 15, 4, 0, tzinfo=UTC)  # 5 days before the 20th
    report = sweep.run_once(store, store, reader, now=now, only={tenant})
    assert report.tenants == 1
    assert len(report.reminded) == 1, "October's period, due 20 November"
    assert len(report.created) == 1, "December entered the window"
    assert report.failed == {}
    assert report.as_json()["now"] == now.isoformat()
    assert report.lines()[0].startswith("obligation-sweep as of 2026-11-15T04:00:00+00:00")
    assert len(store.of_tenant(other)) == 2, "another tenant is left alone"

    reader.down = True
    failed = sweep.run_once(store, store, reader, now=now)
    assert set(failed.failed) == {str(tenant), str(other)}
    assert any(line.startswith("  failed ") for line in failed.lines())


def settings(**overrides: Any) -> ObligationSettings:
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "obligation-sweep",
        "obligation_store": "postgres",
    }
    values.update(overrides)
    return ObligationSettings(**values)


@pytest.mark.parametrize(
    ("argv", "chosen", "why"),
    [
        ([], settings(), "pass --once"),
        (["--once", "--now", "2026-11-15T10:00:00+05:30"], settings(env="staging"), "CW_ENV"),
        (["--once"], settings(obligation_store="memory"), "postgres"),
    ],
)
def test_the_command_refuses_what_it_must_not_do(
    argv: list[str], chosen: ObligationSettings, why: str
) -> None:
    out, err = io.StringIO(), io.StringIO()
    assert sweep.main(argv, settings=chosen, stdout=out, stderr=err) == 2
    assert why in err.getvalue()
    assert out.getvalue() == ""


def test_the_command_reads_its_moment_with_an_offset(capsys: pytest.CaptureFixture[str]) -> None:
    args = sweep.parser().parse_args(
        ["--once", "--now", "2026-11-15T10:00:00+05:30", "--tenant", str(TenantId.new())]
    )
    assert args.now == datetime(2026, 11, 15, 4, 30, tzinfo=UTC)
    for bad in ("2026-11-15T10:00:00", "next tuesday"):
        with pytest.raises(SystemExit):
            sweep.parser().parse_args(["--once", "--now", bad])
    assert "offset" in capsys.readouterr().err


def test_the_report_is_json_when_asked() -> None:
    report = sweep.SweepReport(now=DECIDED_AT, tenants=1, refused={"uncited": 2})
    assert json.loads(json.dumps(report.as_json()))["refused"] == {"uncited": 2}
    assert "  guard refused 2: uncited" in report.lines()
    assert replace(report, failed={"t": "boom"}).lines()[-1] == "  failed t: boom"
