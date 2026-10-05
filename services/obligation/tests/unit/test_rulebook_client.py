"""The rulebook reader against a mock transport: a detail becomes the kernel's snapshot and the
facts the cache keeps (verified citations only, the approvers when named), a read is kept for a
minute unless asked fresh, a 404 is None, and anything else the reader cannot use is
RulebookUnavailableError."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx2
import pytest

from domain_kernel.ids import RuleVersionId, UserId
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import specification_to_mapping
from domain_kernel.rules import RuleVersionSnapshot
from domain_kernel.status import RuleVersionStatus
from obligation.domain.errors import RulebookUnavailableError
from obligation.infrastructure.rulebook_client import (
    HttpRuleVersionReader,
    read_from,
    snapshot_from,
)
from obligation.testing import rule
from py_common.auth import ServiceTokenUnavailableError

NOW = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
APPROVER = UUID(int=0xA11)


def citation(verified: bool, ref: str = "en.p1") -> dict[str, Any]:
    return {
        "citation_id": str(UUID(int=7 if verified else 8)),
        "rule_version_id": str(UUID(int=1)),
        "clause_id": str(UUID(int=9)),
        "document_id": str(UUID(int=10)),
        "clause_ref": ref,
        "quote": "Example clause text (synthetic)",
        "verified": verified,
        "match_score": 0.97 if verified else 0.4,
        "verified_at": "2026-09-29T06:00:00Z" if verified else None,
    }


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
        "seed_status": "needs_review",
        "published_at": "2026-09-30T09:00:00+05:30",
        "approved_by": [str(APPROVER)],
        "citations": [citation(True), citation(False, "en.p2")],
    }
    body.update(overrides)
    return body


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def reader(
    handler: Any, auth: httpx2.Auth | None = None, clock: Clock | None = None
) -> HttpRuleVersionReader:
    client = httpx2.Client(base_url="http://rulebook", transport=httpx2.MockTransport(handler))
    return HttpRuleVersionReader(client=client, auth=auth, clock=clock or Clock())


def test_a_detail_becomes_the_snapshot_and_the_cached_facts() -> None:
    the_rule = rule()
    read = read_from(detail(the_rule), fetched_at=NOW)
    assert read.snapshot == the_rule
    ref = read.ref
    assert (ref.rule_key, ref.status, ref.seed_status) == (
        "gstr3b_monthly",
        RuleVersionStatus.PUBLISHED,
        "needs_review",
    )
    assert ref.approved_by == (UserId(APPROVER),)
    assert ref.published_at == datetime(2026, 9, 30, 3, 30, tzinfo=UTC)
    assert [c.clause_ref for c in ref.citations] == ["en.p1"], "only the verified citation"
    assert ref.citations[0].verified_at == datetime(2026, 9, 29, 6, 0, tzinfo=UTC)
    assert ref.fetched_at == NOW

    older = read_from(detail(the_rule, approved_by=None, published_at=None), fetched_at=NOW)
    assert (older.ref.approved_by, older.ref.published_at) == ((), None), "an older rulebook"


def test_a_read_is_kept_for_a_minute_unless_asked_fresh() -> None:
    the_rule = rule()
    calls: list[str] = []
    status = ["published"]

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.url.path)
        return httpx2.Response(200, json=detail(the_rule, status=status[0]))

    clock = Clock()
    rules = reader(handler, clock=clock)
    first = rules.read(the_rule.rule_version_id)
    assert first is not None
    assert first.snapshot == the_rule
    assert rules.read(the_rule.rule_version_id) == first
    assert calls == [f"/v1/rulebook/rule-versions/{the_rule.rule_version_id}"]

    status[0] = "withdrawn"
    fresh = rules.read(the_rule.rule_version_id, fresh=True)
    assert fresh is not None
    assert fresh.ref.status is RuleVersionStatus.WITHDRAWN
    assert rules.read(the_rule.rule_version_id) == fresh, "the fresh read is kept"
    clock.now += timedelta(seconds=61)
    assert len(calls) == 2
    rules.read(the_rule.rule_version_id)
    assert len(calls) == 3, "a minute later it asks again"
    rules.close()


def test_a_one_off_rule_with_an_end_date() -> None:
    one_off = replace(
        rule(recurrence=None, due_in_days=30),
        effective=EffectivePeriod(date(2026, 4, 1), date(2027, 4, 1)),
    )
    assert snapshot_from(detail(one_off)) == one_off


def test_unknown_is_none_and_the_rest_is_unavailable() -> None:
    assert reader(lambda _: httpx2.Response(404, json={})).read(RuleVersionId.new()) is None
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
        lambda _: httpx2.Response(200, json=detail(the_rule, status="retired")),
        lambda _: httpx2.Response(200, json=detail(the_rule, published_at="2026-09-30T09:00")),
        lambda _: httpx2.Response(200, json={"rule_id": "x"}),
        unreachable,
        no_token,
    ):
        with pytest.raises(RulebookUnavailableError):
            reader(handler).read(the_rule.rule_version_id)


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

    reader(handler, auth=Bearer()).read(the_rule.rule_version_id)
    assert seen == ["Bearer test-token"]
