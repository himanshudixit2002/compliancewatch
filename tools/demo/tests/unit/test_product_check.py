"""The check's steps and the tool's plumbing against a scripted product: what each step waits
for, what it reports, and how it fails. ``test_product_seed.py`` runs the honesty and isolation
steps against the real app; ``make product-check`` runs every step against the dev stack."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

import httpx2
import pytest

from cw_demo.product import check
from cw_demo.product.check import (
    CheckContext,
    NotYetError,
    Step,
    StepFailedError,
    StepResult,
    as_json,
    poll,
    render,
    run_checks,
    select,
    sink_line,
)
from cw_demo.product.client import (
    Product,
    ProductError,
    ProductSettings,
    as_tenant,
    describe,
    loopback,
    ok,
    problem_slug,
    refusal,
)
from cw_demo.product.tenants import BUSINESS_TENANT, DEMO_GSTIN
from py_common.settings import AuthMode, Environment

ENTITY: Final = str(uuid4())
REGISTRATION: Final = str(uuid4())
MONTHLY: Final = str(uuid4())
GROUP_A: Final = str(uuid4())
DISPATCH: Final = str(uuid4())
SINK_ID: Final = f"sink:{DISPATCH}"
LOOPS: Final = dict.fromkeys(
    (*check.CONSUMER_GROUPS, *check.RELAYS, *check.JOBS, "eval/outbox-relay"), True
)


class Scripted:
    """The product's answers to the loop and health steps; ``polls_until_ready`` answers each
    waiting read that many times as not there yet."""

    def __init__(self, *, polls_until_ready: int = 0, card_error: str = "") -> None:
        self.waits = polls_until_ready
        self.card_error = card_error
        self.evaluated: list[str] = []
        self.loops = dict(LOOPS)
        self.starting = 0
        """How many times /ready answers as a proxy does before the app is up."""

    def waiting(self) -> bool:
        if self.waits > 0:
            self.waits -= 1
            return True
        return False

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        path, params = request.url.path, request.url.params
        if path == "/ready" and self.starting > 0:
            self.starting -= 1
            return httpx2.Response(502, text="bad gateway")
        if path == "/ready":
            return httpx2.Response(
                200, json={"status": "ready", "checks": {"rulebook.store": True}}
            )
        if path == "/health":
            return httpx2.Response(200, json={"status": "ok"})
        if path == "/loops":
            body = {
                "status": "ok" if all(self.loops.values()) else "unhealthy",
                "heartbeat_age_seconds": 0.4,
                "loops": self.loops,
                "task_queues": {"pipeline": True},
            }
            return httpx2.Response(200, json=body)
        if path == "/v1/businesses":
            return httpx2.Response(
                200, json={"items": [{"id": ENTITY, "gstins": [DEMO_GSTIN]}], "next_cursor": None}
            )
        if path == f"/v1/businesses/{ENTITY}":
            registrations = [{"id": REGISTRATION, "key": DEMO_GSTIN}]
            return httpx2.Response(200, json={"id": ENTITY, "registrations": registrations})
        if path == "/v1/rulebook/rule-versions":
            return httpx2.Response(
                200,
                json=[
                    {
                        "rule_version_id": MONTHLY,
                        "rule_key": "gstr3b_monthly",
                        "status": "published",
                        "version": 1,
                    },
                    {
                        "rule_version_id": GROUP_A,
                        "rule_key": "gstr3b_quarterly_group_a",
                        "status": "published",
                        "version": 1,
                    },
                ],
            )
        decisions = f"/v1/applicability-engine/businesses/{REGISTRATION}/decisions"
        result = {MONTHLY: "applies", GROUP_A: "not_applicable"}
        if path == decisions and request.method == "POST":
            version = json.loads(request.content)["rule_version_id"]
            self.evaluated.append(version)
            decision = {"result": result[version], "needs_review": False, "decision_id": "d"}
            return httpx2.Response(201, json=decision)
        if path == decisions:
            version = params["rule_version_id"]
            return httpx2.Response(200, json={"items": [{"result": result[version]}]})
        if path == "/v1/obligation/obligations":
            made = [] if self.waiting() else [{"rule_version_id": MONTHLY, "status": "open"}]
            return httpx2.Response(200, json=made)
        if path == f"/v1/rulebook/rule-versions/{MONTHLY}/citations":
            return httpx2.Response(200, json=[{"verified": True}])
        if path == "/v1/notification/notifications":
            return httpx2.Response(200, json={"items": self.cards(), "next_cursor": None})
        return httpx2.Response(404, json={"type": "urn:compliancewatch:problem:route-not-found"})

    def cards(self) -> list[dict[str, Any]]:
        refused = {
            "channel": "whatsapp",
            "state": "failed",
            "occasion": "change_card",
            "provider_message_id": "",
            "error": "whatsapp: outside the 24-hour customer service window",
        }
        sent = {
            "channel": "email",
            "state": "sent",
            "occasion": "change_card",
            "provider_message_id": SINK_ID,
            "error": self.card_error,
        }
        return [refused] if self.card_error else [refused, sent]


@pytest.fixture
def sink(tmp_path: Path) -> Path:
    path = tmp_path / "sink.jsonl"
    path.write_text(json.dumps({"provider_message_id": SINK_ID}) + "\n", encoding="utf-8")
    return path


def scripted_product(script: Scripted, sink: Path) -> Product:
    settings = ProductSettings(
        _env_file=None, service_name="cw-product", notification_sink_path=str(sink)
    )

    def client(name: str) -> httpx2.Client:
        return httpx2.Client(base_url=f"http://{name}", transport=httpx2.MockTransport(script))

    return Product(settings, client("internal"), client("public"), client("worker"))


def context_of(product: Product, timeout: float = 2.0) -> CheckContext:
    return CheckContext(product, timeout=timeout, interval=0.01)


@pytest.fixture
def script() -> Scripted:
    return Scripted(polls_until_ready=2)


@pytest.fixture
def product(script: Scripted, sink: Path) -> Product:
    return scripted_product(script, sink)


def test_the_loop_evaluates_and_waits_for_obligations_and_the_change_card(
    script: Scripted, product: Product
) -> None:
    lines = check.loop(context_of(product))
    assert script.evaluated == [MONTHLY, GROUP_A]
    assert lines[0] == "decisions: gstr3b_monthly applies, gstr3b_quarterly_group_a not_applicable"
    assert lines[1] == "obligations: gstr3b_monthly 1 (1 verified citations)"
    assert lines[2] == f"change card: email sent through the sink ({SINK_ID})"
    assert lines[3].startswith("also: whatsapp failed: whatsapp: outside the 24-hour")
    assert lines[4].endswith("holds the message")


def test_the_loop_fails_when_no_change_card_reaches_the_sink(sink: Path) -> None:
    product = scripted_product(Scripted(card_error="email failed"), sink)
    with pytest.raises(StepFailedError, match="no change card sent through the sink yet"):
        check.loop(context_of(product, timeout=0.05))


def test_the_health_step_lists_the_worker_loops(product: Product) -> None:
    lines = check.health(context_of(product))
    assert lines[0] == "internal listener ready: 1 checks ok"
    assert "obligation.decisions" in lines[3]
    assert "applicability-engine" in lines[4]
    assert lines[5] == "task queues: pipeline"


def test_the_health_step_waits_through_a_listener_that_is_starting(
    script: Scripted, product: Product
) -> None:
    script.starting = 2
    assert check.health(context_of(product))[0] == "internal listener ready: 1 checks ok"
    script.starting = 1000
    with pytest.raises(StepFailedError, match="/ready on the internal listener: 502"):
        check.health(context_of(product, timeout=0.05))


def test_the_health_step_names_a_loop_that_is_not_running(
    script: Scripted, product: Product
) -> None:
    script.loops["notification/consumer:notification.obligations"] = False
    with pytest.raises(StepFailedError, match=r"notification\.obligations"):
        check.health(context_of(product, timeout=0.05))


def test_the_sink_line_is_found_or_reported(sink: Path, tmp_path: Path) -> None:
    assert sink_line(sink, SINK_ID).endswith("holds the message")
    assert "not on this machine" in sink_line(tmp_path / "elsewhere.jsonl", SINK_ID)
    with pytest.raises(StepFailedError, match="has no line"):
        sink_line(sink, "sink:another")


def test_poll_returns_once_the_condition_holds_and_fails_after_the_timeout() -> None:
    now = [0.0]
    answers: Iterator[Exception | str] = iter(
        [NotYetError("one"), httpx2.ConnectError("refused"), "done"]
    )

    def condition() -> str:
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def sleep(seconds: float) -> None:
        now[0] += seconds

    assert poll(condition, timeout=10, interval=1, clock=lambda: now[0], sleep=sleep) == "done"
    assert now[0] == 2.0

    def never() -> str:
        raise NotYetError("no obligation yet for gstr3b_monthly")

    with pytest.raises(StepFailedError, match="still so after 3 s"):
        poll(never, timeout=3, interval=1, clock=lambda: now[0], sleep=sleep)


def test_steps_run_in_order_and_one_failure_does_not_stop_the_next(product: Product) -> None:
    def failing(_: CheckContext) -> list[str]:
        raise ProductError("GET /v1/x: 503 rulebook-publishing-disabled")

    def broken(_: CheckContext) -> list[str]:
        raise httpx2.ReadTimeout("slow")

    def surprised(_: CheckContext) -> list[str]:
        raise KeyError("items")

    steps = [
        Step("first", "fails", failing),
        Step("second", "breaks", broken),
        Step("third", "surprised", surprised),
        Step("fourth", "passes", lambda _: ["fine"]),
    ]
    ticks = iter([0.0, 1.0, 1.0, 2.5, 2.5, 2.6, 2.6, 3.0])
    results = run_checks(context_of(product), steps, clock=lambda: next(ticks))
    assert [(r.name, r.ok, r.seconds) for r in results] == [
        ("first", False, 1.0),
        ("second", False, 1.5),
        ("third", False, 0.1),
        ("fourth", True, 0.4),
    ]
    assert results[1].error == "ReadTimeout: slow"
    assert results[2].error == "KeyError: 'items'"
    text = render(results)
    assert "FAILED  first" in text
    assert "        - fine" in text
    assert text.endswith("1 of 4 steps passed.\n")
    report = as_json(results)
    assert report["ok"] is False
    assert [step["name"] for step in report["steps"]] == ["first", "second", "third", "fourth"]


def test_steps_are_chosen_by_name_in_the_check_order() -> None:
    assert [step.name for step in check.STEPS] == ["health", "honesty", "loop", "isolation"]
    assert [step.name for step in select(["isolation", "health"])] == ["health", "isolation"]
    assert select(None) == check.STEPS
    with pytest.raises(ProductError, match="no step nope"):
        select(["nope"])


def test_a_step_result_reports_its_error_line() -> None:
    result = StepResult("loop", "a loop", ok=False, seconds=30.1, error="no obligation yet")
    assert "        error: no obligation yet" in render([result])


@pytest.mark.parametrize(
    ("env", "auth_mode", "allowed"),
    [
        ("local", "header", True),
        ("test", "dual", True),
        ("local", "token", False),
        ("staging", "header", False),
    ],
)
def test_the_refusals(env: Environment, auth_mode: AuthMode, allowed: bool) -> None:
    settings = ProductSettings(
        _env_file=None, service_name="cw-product", env=env, auth_mode=auth_mode
    )
    assert (refusal(settings) is None) is allowed


def test_loopback_and_the_answers_the_tool_reads() -> None:
    assert loopback("::") == "127.0.0.1"
    assert loopback("0.0.0.0") == "127.0.0.1"
    assert loopback("127.0.0.1") == "127.0.0.1"
    assert loopback("::1") == "[::1]"
    request = httpx2.Request("POST", "http://internal/v1/rulebook/rule-versions/x/approve")
    problem = httpx2.Response(
        409,
        json={"type": "urn:compliancewatch:problem:rulebook-duplicate-approver", "detail": "twice"},
        request=request,
    )
    assert problem_slug(problem) == "rulebook-duplicate-approver"
    assert describe(problem) == "409 rulebook-duplicate-approver: twice"
    with pytest.raises(ProductError, match="approve: 409 rulebook-duplicate-approver"):
        ok(problem)
    plain = httpx2.Response(502, text="bad gateway", request=request)
    assert (problem_slug(plain), describe(plain)) == ("", "502 bad gateway")
    assert ok(httpx2.Response(204, request=request), 204) is None
    assert as_tenant(BUSINESS_TENANT.tenant_id, extra="1") == {
        "x-tenant-id": str(BUSINESS_TENANT.tenant_id),
        "extra": "1",
    }


def test_a_missing_token_is_named(product: Product) -> None:
    with pytest.raises(ProductError, match="CW_RULEBOOK_REVIEW_TOKEN is not set"):
        product.review_headers()
    with pytest.raises(ProductError, match="CW_RULEBOOK_WRITE_TOKEN is not set"):
        product.write_headers()
