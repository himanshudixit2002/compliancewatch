"""The rulebook reader against a mock transport: a detail becomes the kernel's snapshot, a 404
is None, and anything else the reader cannot use is RulebookUnavailableError."""

from dataclasses import replace
from datetime import date
from typing import Any

import httpx2
import pytest

from domain_kernel.ids import RuleVersionId
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import specification_to_mapping
from domain_kernel.rules import RuleVersionSnapshot
from obligation.domain.errors import RulebookUnavailableError
from obligation.infrastructure.rulebook_client import HttpRuleVersionReader, snapshot_from
from obligation.testing import rule
from py_common.auth import ServiceTokenUnavailableError


def detail(snapshot: RuleVersionSnapshot, **overrides: Any) -> dict[str, Any]:
    """What GET /v1/rulebook/rule-versions/{id} answers for ``snapshot``."""
    body: dict[str, Any] = {
        "rule_version_id": str(snapshot.rule_version_id),
        "rule_id": str(snapshot.rule_id),
        "rule_key": "gstr3b_monthly",
        "regulator": snapshot.regulator,
        "level": "central",
        "version": snapshot.version,
        "status": "published",
        "title": snapshot.title,
        "summary": "A monthly filer furnishes FORM GSTR-3B.",
        "specification": specification_to_mapping(snapshot.specification),
        "obligation_template": snapshot.obligation_template.to_mapping(),
        "recurrence": None if snapshot.recurrence is None else snapshot.recurrence.to_mapping(),
        "effective_from": snapshot.effective.start.isoformat(),
        "effective_to": None
        if snapshot.effective.end is None
        else snapshot.effective.end.isoformat(),
        "source": {"instrument": "CGST Rules, 2017", "reference": "rule 61(1)"},
        "citations": [],
    }
    body.update(overrides)
    return body


def reader(handler: Any, auth: httpx2.Auth | None = None) -> HttpRuleVersionReader:
    client = httpx2.Client(base_url="http://rulebook", transport=httpx2.MockTransport(handler))
    return HttpRuleVersionReader(client=client, auth=auth)


def test_a_detail_becomes_the_snapshot_and_is_read_once() -> None:
    the_rule = rule()
    calls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.url.path)
        return httpx2.Response(200, json=detail(the_rule))

    rules = reader(handler)
    assert rules.get(the_rule.rule_version_id) == the_rule
    assert rules.get(the_rule.rule_version_id) == the_rule
    assert calls == [f"/v1/rulebook/rule-versions/{the_rule.rule_version_id}"]
    rules.close()


def test_a_one_off_rule_with_an_end_date() -> None:
    one_off = replace(
        rule(recurrence=None, due_in_days=30),
        effective=EffectivePeriod(date(2026, 4, 1), date(2027, 4, 1)),
    )
    assert snapshot_from(detail(one_off)) == one_off


def test_unknown_is_none_and_the_rest_is_unavailable() -> None:
    assert reader(lambda _: httpx2.Response(404, json={})).get(RuleVersionId.new()) is None
    the_rule = rule()

    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    def no_token(request: httpx2.Request) -> httpx2.Response:
        raise ServiceTokenUnavailableError("identity down")

    for handler in (
        lambda _: httpx2.Response(500, text="boom"),
        lambda _: httpx2.Response(403, json={}),
        lambda _: httpx2.Response(200, text="not json"),
        lambda _: httpx2.Response(200, json=detail(the_rule, specification={"bogus": 1})),
        lambda _: httpx2.Response(200, json={"rule_id": "x"}),
        unreachable,
        no_token,
    ):
        with pytest.raises(RulebookUnavailableError):
            reader(handler).get(the_rule.rule_version_id)


def test_the_service_token_goes_with_every_read() -> None:
    the_rule = rule()
    seen: list[str | None] = []

    class Bearer(httpx2.Auth):
        def auth_flow(self, request: httpx2.Request) -> Any:
            request.headers["authorization"] = "Bearer test-token"
            yield request

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers.get("authorization"))
        return httpx2.Response(200, json=detail(the_rule))

    reader(handler, auth=Bearer()).get(the_rule.rule_version_id)
    assert seen == ["Bearer test-token"]
