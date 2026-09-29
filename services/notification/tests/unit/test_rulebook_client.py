from datetime import date, timedelta
from typing import Any

import httpx2
import pytest

from domain_kernel.ids import RuleVersionId
from notification.domain.errors import DependencyRefusedError, DependencyUnavailableError
from notification.domain.ports import RuleVersionFacts
from notification.infrastructure.rulebook_client import HttpRuleVersionReader, facts_from
from notification.testing import FakeClock

RULE = RuleVersionId.new()
DETAIL: dict[str, Any] = {
    "rule_version_id": str(RULE),
    "title": "File FORM GSTR-3B every month",
    "summary": "A monthly filer furnishes FORM GSTR-3B.",
    "effective_from": "2026-04-01",
    "obligation_template": {
        "title": "File GSTR-3B for the month",
        "steps": ["Reconcile", "File", " "],
    },
    "source": {"instrument": "CGST Rules, 2017", "reference": "rule 61(1)", "note": "n"},
    "citations": [],
}


def reader(handler: Any, clock: FakeClock | None = None) -> HttpRuleVersionReader:
    client = httpx2.Client(base_url="http://rulebook", transport=httpx2.MockTransport(handler))
    return HttpRuleVersionReader(client=client, clock=clock or FakeClock())


def test_reads_the_facts_and_keeps_them_for_an_hour() -> None:
    calls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.url.path)
        return httpx2.Response(200, json=DETAIL)

    clock = FakeClock()
    rules = reader(handler, clock)
    facts = rules.get(RULE)
    assert facts == RuleVersionFacts(
        title="File GSTR-3B for the month",
        summary="A monthly filer furnishes FORM GSTR-3B.",
        effective_from=date(2026, 4, 1),
        steps=("Reconcile", "File"),
        source_ref="CGST Rules, 2017, rule 61(1)",
    )
    assert rules.get(RULE) == facts
    assert calls == [f"/v1/rulebook/rule-versions/{RULE}"]
    clock.advance(timedelta(hours=1).total_seconds())
    rules.get(RULE)
    assert len(calls) == 2
    rules.close()


def test_an_unknown_version_is_none_and_an_outage_is_dependency_unavailable() -> None:
    assert reader(lambda _: httpx2.Response(404, json={})).get(RULE) is None
    failing = [
        lambda _: httpx2.Response(503, text="down"),
        lambda _: httpx2.Response(429, text="slow down"),
        lambda _: httpx2.Response(408, text="timed out"),
        lambda _: httpx2.Response(200, text="not json"),
        lambda _: httpx2.Response(200, json=["a list"]),
        lambda _: httpx2.Response(200, json={**DETAIL, "effective_from": "soon"}),
    ]
    for handler in failing:
        with pytest.raises(DependencyUnavailableError):
            reader(handler).get(RULE)

    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    with pytest.raises(DependencyUnavailableError, match="unreachable"):
        reader(unreachable).get(RULE)


@pytest.mark.parametrize("status", [400, 401, 403, 409, 422])
def test_a_refusal_other_than_404_408_and_429_is_permanent(status: int) -> None:
    calls: list[int] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(status)
        return httpx2.Response(status, text="refused")

    rules = reader(handler)
    with pytest.raises(DependencyRefusedError, match=f"refused rule version {RULE}: {status}"):
        rules.get(RULE)
    with pytest.raises(DependencyRefusedError):
        rules.get(RULE)
    assert calls == [status, status], "a refusal is not kept"


def test_facts_fall_back_to_the_rule_title_and_cite_what_there_is() -> None:
    facts = facts_from(
        {"title": "Rule", "effective_from": "2026-04-01", "source": {"instrument": "Act"}}
    )
    assert (facts.title, facts.summary, facts.steps, facts.source_ref) == ("Rule", "", (), "Act")
    with pytest.raises(TypeError):
        facts_from({**DETAIL, "obligation_template": {"steps": "one"}})
