"""The check's steps and the tool's plumbing against a scripted product: what each step waits
for, what it reports, and how it fails. ``test_product_seed.py`` runs the honesty and isolation
steps against the real app; ``make product-check`` runs every step against the dev stack."""

import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

import httpx2
import pytest

from cw_demo.product import check
from cw_demo.product.analysts import REVIEWERS
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
                "task_queues": {"applicability": True, "pipeline": True},
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


def scripted_product(script: Scripted, sink: Path, **settings_values: Any) -> Product:
    settings = ProductSettings(
        _env_file=None,
        service_name="cw-product",
        notification_sink_path=str(sink),
        **settings_values,
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
    assert "applicability-engine.rules" in lines[3]
    assert lines[5] == "task queues: applicability, pipeline"


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
    assert [step.name for step in check.STEPS] == [
        "health",
        "honesty",
        "loop",
        "isolation",
        "recompute",
        "fanout",
        "reminders",
        "rollback",
        "tracking",
        "changes",
        "public",
        "sources",
    ]
    assert [step.name for step in select(["isolation", "health"])] == ["health", "isolation"]
    assert select(None) == check.STEPS
    with pytest.raises(ProductError, match="no step nope"):
        select(["nope"])


def test_the_recompute_step_needs_the_monthly_rule_published(sink: Path) -> None:
    class Unpublished(Scripted):
        def __call__(self, request: httpx2.Request) -> httpx2.Response:
            if request.url.path == "/v1/rulebook/rule-versions":
                return httpx2.Response(200, json=[])
            return super().__call__(request)

    product = scripted_product(Unpublished(), sink)
    with pytest.raises(StepFailedError, match="gstr3b_monthly is not published"):
        check.recompute(context_of(product))


def test_the_tracking_step_needs_the_monthly_rule_published(sink: Path) -> None:
    class Unpublished(Scripted):
        def __call__(self, request: httpx2.Request) -> httpx2.Response:
            if request.url.path == "/v1/rulebook/rule-versions":
                return httpx2.Response(200, json=[])
            return super().__call__(request)

    product = scripted_product(Unpublished(), sink)
    with pytest.raises(StepFailedError, match="gstr3b_monthly is not published"):
        check.tracking(context_of(product))


PROBE: Final = check.Probe("Tracking probe (synthetic)", "29ZZZAA0000Z1Z5", ENTITY, str(uuid4()))
MONTHLY_VERSION: Final[dict[str, Any]] = {
    "rule_version_id": MONTHLY,
    "rule_key": "gstr3b_monthly",
    "recurrence": {"frequency": "monthly", "due_day": 20, "due_month_offset": 0},
    "effective_from": "2026-04-01",
}


class Decided(Scripted):
    """The engine lists the probe's decisions, made at ``instants`` with ``result``."""

    def __init__(self, *instants: str, result: str = "applies") -> None:
        super().__init__()
        self.instants = instants
        self.result = result

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == f"{check.ENGINE}/businesses/{PROBE.registration_id}/decisions":
            items = [{"result": self.result, "decided_at": at} for at in self.instants]
            return httpx2.Response(200, json={"items": items, "next_cursor": None})
        return super().__call__(request)


def due_next(script: Decided, sink: Path, **version: Any) -> tuple[str, str, str]:
    decided, period, due_on = check.due_next(
        context_of(scripted_product(script, sink)), PROBE, {**MONTHLY_VERSION, **version}
    )
    return decided.isoformat(), period.label, due_on.isoformat()


def test_the_return_due_next_is_the_period_still_due_on_the_day_of_the_first_decision(
    sink: Path,
) -> None:
    newest_first = Decided("2026-10-25T04:00:00Z", "2026-10-05T18:30:00Z")
    assert due_next(newest_first, sink) == ("2026-10-06", "2026-09", "2026-10-20"), (
        "6 October in India; September is due on the 20th"
    )
    assert due_next(Decided("2026-10-25T04:00:00Z"), sink) == (
        "2026-10-25",
        "2026-10",
        "2026-11-20",
    )
    assert due_next(Decided("2026-10-06T04:00:00Z"), sink, effective_from="2026-10-01") == (
        "2026-10-06",
        "2026-10",
        "2026-11-20",
    ), "September ended before the version took effect"
    quarterly = {"frequency": "quarterly", "due_day": 22, "due_month_offset": 0}
    assert due_next(Decided("2026-10-06T04:00:00Z"), sink, recurrence=quarterly) == (
        "2026-10-06",
        "2026-27 Q2",
        "2026-10-22",
    )
    with pytest.raises(StepFailedError, match="no decision that it applies"):
        due_next(Decided("2026-10-06T04:00:00Z", result="not_applicable"), sink)


def test_a_title_names_the_form_as_a_whole_code() -> None:
    assert check.names_form("File GSTR-3B for the month (2026-09)", "GSTR-3B")
    assert check.names_form("File GSTR - 3B for the quarter", "GSTR-3B")
    assert not check.names_form("File GSTR-3BA", "GSTR-3B")
    assert not check.names_form("File GSTR-3 for the year", "GSTR-3B")


def tracked(**overrides: Any) -> dict[str, Any]:
    """A detail as the tracking step reads it after its changes, with ``overrides``."""
    detail: dict[str, Any] = {
        "history": [{"kind": kind} for kind in check.TRACKED_HISTORY],
        "rule_version": {
            "approved_by": [str(reviewer.user_id) for reviewer in REVIEWERS],
            "seed_status": "needs_review",
            "reviewed": False,
            "published_at": "2026-10-01T04:00:00Z",
        },
        "citations": [{"clause_ref": "en.p1"}],
        "comments": [{"comment_id": "c1"}],
    }
    detail.update(overrides)
    return detail


def test_the_tracked_detail_names_both_reviewers_and_refuses_what_is_missing() -> None:
    comment = {"comment_id": "c1"}
    assert check.tracked_detail(tracked(), comment) == (
        "Demo reviewer one (synthetic) and Demo reviewer two (synthetic)"
    )
    review = tracked()["rule_version"]
    for detail, problem in (
        (tracked(history=[{"kind": "created"}]), "history reads created"),
        (tracked(rule_version=None), "no facts"),
        (tracked(rule_version={**review, "approved_by": [str(uuid4())]}), "not both"),
        (tracked(rule_version={**review, "seed_status": "reviewed"}), "reviews nothing"),
        (tracked(citations=[]), "no verified citation"),
        (tracked(comments=[]), "does not list the comment"),
    ):
        with pytest.raises(StepFailedError, match=problem):
            check.tracked_detail(detail, comment)


class Completing(Scripted):
    """Answers every request with an obligation of ``status``, the second one on replayed when
    ``replayed``."""

    def __init__(self, replayed: bool, status: str = "done") -> None:
        super().__init__()
        self.replayed, self.status, self.calls = replayed, status, 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.calls += 1
        headers = {"Idempotent-Replayed": "true"} if self.replayed and self.calls > 1 else {}
        return httpx2.Response(200, json={"status": self.status}, headers=headers)


def test_completing_twice_needs_the_same_answer_replayed(sink: Path) -> None:
    def answering(replayed: bool, status: str = "done") -> Product:
        return scripted_product(Completing(replayed, status), sink)

    keyed = check.keyed({"x-tenant-id": str(uuid4())}, "same-key-1")
    completed, replayed = check.complete_twice(answering(True), "/x", keyed)
    assert (completed["status"], replayed) == ("done", "true")
    with pytest.raises(StepFailedError, match="not replayed"):
        check.complete_twice(answering(False), "/x", keyed)
    with pytest.raises(StepFailedError, match="is open"):
        check.complete_twice(answering(True, "open"), "/x", keyed)


def test_the_probe_gstins_are_made_up_karnataka_ones() -> None:
    made = {check.probe_gstin(token) for token in (0, 1, 26, 677, 2**64)}
    assert len(made) == 5
    assert all(gstin.startswith("29ZZZ") and gstin.endswith("Z1Z5") for gstin in made)
    assert check.probe_gstin(0) == "29ZZZAA0000Z1Z5"


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


def test_the_fanout_step_needs_the_records_it_reads(product: Product) -> None:
    with pytest.raises(StepFailedError, match="CW_PRODUCT_RECORDS_URL"):
        check.fanout(context_of(product))


def test_the_changes_step_needs_the_records_it_reads(product: Product) -> None:
    with pytest.raises(StepFailedError, match="CW_PRODUCT_RECORDS_URL"):
        check.changes(context_of(product))


def test_the_feed_item_names_both_reviewers_and_refuses_what_is_missing() -> None:
    item = {
        "rule_key": "gstr9_annual",
        "approved_by": [str(analyst.user_id) for analyst in REVIEWERS],
        "seed_status": "needs_review",
        "citations": [{"quote": "an example quote (synthetic)"}],
    }
    names = check.feed_reviewers(item)
    assert names == " and ".join(analyst.name for analyst in REVIEWERS)
    for change, message in (
        ({"approved_by": item["approved_by"][:1]}, "not both synthetic reviewers"),
        ({"seed_status": "reviewed"}, "a synthetic approval reviews nothing"),
        ({"citations": []}, "cites no verified clause"),
    ):
        with pytest.raises(StepFailedError, match=message):
            check.feed_reviewers({**item, **change})


def test_the_rollback_step_is_skipped_unless_destructive(product: Product) -> None:
    (rollback,) = select(["rollback"])
    (result,) = run_checks(context_of(product), [rollback])
    assert (result.ok, result.skipped, result.details) == (
        True,
        True,
        ["skipped (destructive; CI runs it)"],
    )
    text = render([result])
    assert "skip    rollback" in text
    assert text.endswith("1 of 1 steps passed.\n")
    assert as_json([result])["steps"][0]["skipped"] is True


OBLIGATION: Final = str(uuid4())
DUE_AT: Final = "2026-11-20T18:29:59Z"


class Reminding(Scripted):
    """The business tenant's open obligation, and a reminder about it once the sweep sent one."""

    def __init__(self, *, reminded: bool = True) -> None:
        super().__init__()
        self.reminded = reminded
        self.swept: list[list[str]] = []

    def sweep(self, arguments: Sequence[str]) -> tuple[int, dict[str, Any]]:
        self.swept.append(list(arguments))
        reminded = [OBLIGATION] if self.reminded and len(self.swept) == 2 else []
        return 0, {"reminded": reminded, "created": [], "tenants": 1}

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/v1/obligation/obligations":
            obligation = {
                "obligation_id": OBLIGATION,
                "title": "File GSTR-3B (2026-10)",
                "status": "open",
                "due_at": DUE_AT,
            }
            return httpx2.Response(200, json=[obligation])
        if path == "/v1/notification/notifications":
            items = []
            if len(self.swept) >= 2 and self.reminded:
                items = [
                    {
                        "id": "n1",
                        "obligation_id": OBLIGATION,
                        "occasion": "reminder",
                        "channel": "email",
                        "state": "sent",
                        "provider_message_id": SINK_ID,
                    }
                ]
            return httpx2.Response(200, json={"items": items, "next_cursor": None})
        return super().__call__(request)


def test_the_reminders_step_sweeps_before_the_due_date_until_a_reminder_goes(sink: Path) -> None:
    script = Reminding()
    product = scripted_product(script, sink)
    context = CheckContext(product, timeout=2.0, interval=0.01, sweep=script.sweep)
    lines = check.reminders(context)
    assert [arguments[1] for arguments in script.swept] == [
        "2026-11-15T18:29:59+00:00",
        "2026-11-18T18:29:59+00:00",
    ], "5 days before, then 2"
    assert all(
        arguments[2:] == ["--tenant", str(BUSINESS_TENANT.tenant_id)] for arguments in script.swept
    )
    assert lines[1].startswith("reminded: File GSTR-3B (2026-10), due 2026-11-20T18:29:59Z")
    assert lines[2] == f"reminder: email sent through the sink ({SINK_ID})"
    assert lines[3].endswith("holds the message")


def test_the_reminders_step_fails_when_nothing_is_reminded(sink: Path) -> None:
    script = Reminding(reminded=False)
    product = scripted_product(script, sink)
    context = CheckContext(product, timeout=2.0, interval=0.01, sweep=script.sweep)
    with pytest.raises(StepFailedError, match="each was reminded at every threshold"):
        check.reminders(context)
    assert len(script.swept) == 3

    def refused(arguments: Sequence[str]) -> tuple[int, dict[str, Any]]:
        return 2, {"error": "obligation-sweep: refused: --now ..."}

    with pytest.raises(StepFailedError, match="exited 2"):
        check.reminders(CheckContext(product, timeout=2.0, interval=0.01, sweep=refused))


class Sources(Scripted):
    """The pipeline's source manager: the built-in sources, a fetch answered with
    ``fetch_status`` (503 crawl-disabled while crawling is off), the task queue, and an upload
    answered with ``upload_status`` (415 for a file that is no document), which stores a
    document when ``stores`` is set."""

    def __init__(
        self,
        *,
        fetch_status: int = 503,
        probe_status: int = 503,
        upload_status: int = 415,
        stores: bool = False,
    ) -> None:
        super().__init__()
        self.fetch_status = fetch_status
        self.probe_status = probe_status
        self.upload_status = upload_status
        self.stores = stores
        self.fetched: list[str] = []
        self.uploaded: list[str] = []
        self.runs: dict[str, str | None] = dict.fromkeys(check.BUILT_IN_SOURCES)
        self.documents: dict[str, int] = dict.fromkeys(check.BUILT_IN_SOURCES, 0)

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if request.url.host == "public" and path.startswith("/v1/pipeline"):
            return httpx2.Response(
                404, json={"type": "urn:compliancewatch:problem:route-not-found"}
            )
        if path == check.SOURCES:
            return httpx2.Response(200, json={"items": [self.item(key) for key in self.runs]})
        if path == check.TASKS:
            assert request.url.params["status"] == "open"
            return httpx2.Response(200, json={"items": [], "next_cursor": None})
        if path.endswith("/uploads"):
            key = path.split("/")[-2]
            assert request.headers["x-cw-write-token"] == "test-write-token"
            assert b'filename="check.txt"' in request.content
            self.uploaded.append(key)
            if self.stores:
                self.documents[key] += 1
            if self.upload_status == 202:
                return httpx2.Response(202, json={"duplicate": False})
            slug = check.UPLOAD_UNSUPPORTED
            return httpx2.Response(
                self.upload_status, json={"type": f"urn:compliancewatch:problem:{slug}"}
            )
        if path.endswith("/fetch"):
            key = path.split("/")[-2]
            self.fetched.append(key)
            status = self.probe_status if key == check.NO_SOURCE else self.fetch_status
            if status == 202:
                self.runs[key] = str(uuid4())
                return httpx2.Response(202, json={"run_id": self.runs[key]})
            slug = "pipeline-source-not-found" if status == 404 else check.CRAWL_DISABLED
            return httpx2.Response(status, json={"type": f"urn:compliancewatch:problem:{slug}"})
        return super().__call__(request)

    def item(self, key: str) -> dict[str, Any]:
        run = self.runs[key]
        return {
            "key": key,
            "name": key.replace("_", " "),
            "regulator": "CBIC",
            "cadence_seconds": 7200,
            "status": "healthy",
            "freshness": {"state": "never"},
            "latest_run": None if run is None else {"run_id": run},
            "listable": key not in check.STATUTE_SOURCES,
            "document_count": self.documents.get(key, 0),
        }


def with_token(script: Sources, sink: Path) -> Product:
    return scripted_product(script, sink, rulebook_write_token="test-write-token")


def test_the_sources_step_lists_the_sources_and_proves_the_fetch_refused(sink: Path) -> None:
    script = Sources()
    lines = check.sources(context_of(with_token(script, sink)))
    assert lines[0].startswith("sources: the 8 built-in ones listed (cbic_circulars healthy, ")
    assert lines[1] == (
        "fetch refused while crawling is off: 503 pipeline-crawl-disabled, no crawl run recorded"
    )
    assert lines[2] == "GET /v1/pipeline/sources on the public listener: 404 route-not-found"
    assert lines[4:] == [
        "statutes upload-only: cgst_act, cgst_rules, igst_act",
        "GET /v1/pipeline/tasks?status=open: 0 open on the first page",
        "an upload that is no document refused: 415 pipeline-upload-unsupported, nothing stored",
    ]
    assert script.fetched == [check.NO_SOURCE, check.FETCHED_SOURCE]
    assert script.uploaded == ["cgst_rules"]


def test_the_sources_step_fails_when_a_statute_can_be_crawled(sink: Path) -> None:
    class Crawlable(Sources):
        def item(self, key: str) -> dict[str, Any]:
            return {**super().item(key), "listable": True}

    with pytest.raises(StepFailedError, match="must be upload-only: cgst_act, cgst_rules"):
        check.sources(context_of(with_token(Crawlable(), sink)))


def test_the_sources_step_fails_when_an_upload_that_is_no_document_is_taken(sink: Path) -> None:
    with pytest.raises(StepFailedError, match="uploads answered 202"):
        check.sources(context_of(with_token(Sources(upload_status=202), sink)))
    with pytest.raises(StepFailedError, match="the refused upload stored a document"):
        check.sources(context_of(with_token(Sources(stores=True), sink)))


def test_the_sources_step_counts_other_sources_without_judging_them(sink: Path) -> None:
    class WithOthers(Sources):
        def item(self, key: str) -> dict[str, Any]:
            found = super().item(key)
            return {**found, "regulator": None} if key == "sample" else found

    script = WithOthers()
    script.runs["sample"] = None
    lines = check.sources(context_of(with_token(script, sink)))
    assert lines[0].endswith(", and 1 more")


def test_the_sources_step_stops_before_a_real_source_when_crawling_is_on(sink: Path) -> None:
    script = Sources(probe_status=404, fetch_status=202)
    with pytest.raises(StepFailedError, match="crawling is on in this product"):
        check.sources(context_of(with_token(script, sink)))
    assert script.fetched == [check.NO_SOURCE], "no real source was fetched"


def test_the_sources_step_fails_when_a_crawl_starts(sink: Path) -> None:
    script = Sources(fetch_status=202)
    with pytest.raises(StepFailedError, match="a crawl of cbic_notifications started"):
        check.sources(context_of(with_token(script, sink)))


def test_the_sources_step_waits_for_the_built_in_sources(sink: Path) -> None:
    script = Sources()
    del script.runs["gstn_advisories"]
    with pytest.raises(StepFailedError, match="lacks gstn_advisories"):
        check.sources(context_of(with_token(script, sink), timeout=0.05))
