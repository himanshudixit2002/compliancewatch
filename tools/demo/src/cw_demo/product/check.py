"""``cw-product check``: prove that the running product works, one named step after another.

``STEPS`` is the ordered list the check runs; a later package appends its own ``Step`` (engine
recompute on profile.updated, fan-out on rule.published, obligation tracking, the changes feed,
rollback) and the command runs it after these. A step returns the lines it reports and raises
``StepFailedError`` with what is wrong. Whatever it waits for it polls with ``poll``, up to the
check's timeout (``TIMEOUT_SECONDS``, about 30 s), since the worker gets there a few seconds after
the API answers. One failed step does not stop the next.

- ``health``: the internal listener's ``/ready`` has every service's checks ok, the public
  listener answers ``/health``, and the worker's ``/loops`` lists the consumer groups, outbox
  relays, periodic jobs and Temporal task queue the chain needs, each of them running.
- ``honesty``: every published seed rule is one the golden world cites from a recorded quote and
  still reads needs_review, every other seed rule is still a draft, no version of any seed rule is
  marked reviewed, and the golden world and the extraction cases it cites are drafts nobody
  reviewed.
- ``loop``: the business tenant's registration is evaluated (``evaluate``, the trigger until the
  engine has its own); its latest decision of each published rule is the one its answers call for
  (``tenants.SyntheticBusiness.expected``); each rule that applies has obligations, and each such
  rule version cites at least one verified clause; and a change card (the notification
  obligation.created makes) about the business reached sent or delivered through the sink, whose
  file holds its line when this machine can read it.
- ``isolation``: the CA firm's tenant reads none of the business tenant's decisions, obligations,
  notifications or business, and the business tenant none of the CA firm's clients'.
"""

import json
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx2

from cw_demo.product.client import GOLDEN, Product, ProductError, as_tenant, ok
from cw_demo.product.evaluate import (
    SeededRegistration,
    evaluate,
    published_in_force,
    registrations,
    today_in_india,
)
from cw_demo.product.publish import RULEBOOK, rule_versions, supported
from cw_demo.product.tenants import APPLIES, BUSINESS_TENANT, CA_FIRM_TENANT, SyntheticTenant
from cw_evals.qa.world import load_world
from notification.infrastructure.sink import MESSAGE_ID_PREFIX
from ontology import load as load_ontology
from rulebook.application.seed_loader import load_calendar

TIMEOUT_SECONDS: Final = 30.0
POLL_SECONDS: Final = 1.0
ENGINE: Final = "/v1/applicability-engine"
OBLIGATIONS: Final = "/v1/obligation/obligations"
NOTIFICATIONS: Final = "/v1/notification/notifications"
CHANGE_CARD: Final = "change_card"
SENT_STATES: Final = frozenset({"sent", "delivered", "read"})
CONSUMER_GROUPS: Final = (
    "obligation/consumer:obligation.decisions",
    "notification/consumer:notification.obligations",
)
RELAYS: Final = (
    "profile/outbox-relay",
    "rulebook/outbox-relay",
    "applicability-engine/outbox-relay",
    "obligation/outbox-relay",
    "notification/outbox-relay",
)
JOBS: Final = ("notification/notification-dispatch", "obligation/obligation-reminder-sweep")
TASK_QUEUES: Final = ("pipeline",)
REVIEWED: Final = "reviewed"


class StepFailedError(Exception):
    """A step's condition does not hold; the message says what is wrong."""


class NotYetError(Exception):
    """A condition does not hold yet; ``poll`` asks again until its timeout."""


@dataclass(frozen=True, slots=True)
class CheckContext:
    product: Product
    timeout: float = TIMEOUT_SECONDS
    golden: Path = GOLDEN
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    interval: float = POLL_SECONDS


@dataclass(frozen=True, slots=True)
class Step:
    name: str
    summary: str
    run: Callable[[CheckContext], list[str]]


@dataclass
class StepResult:
    name: str
    summary: str
    ok: bool
    seconds: float
    details: list[str] = field(default_factory=list)
    error: str = ""


def poll[T](
    condition: Callable[[], T],
    *,
    timeout: float,
    interval: float = POLL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """``condition()`` once it stops raising ``NotYetError`` (or a connection error, while a process
    is still starting); ``StepFailedError`` with its last reason after ``timeout`` seconds."""
    deadline = clock() + timeout
    while True:
        try:
            return condition()
        except (NotYetError, httpx2.TransportError) as exc:
            reason = str(exc) or type(exc).__name__
            if clock() >= deadline:
                raise StepFailedError(f"{reason} (still so after {timeout:.0f} s)") from exc
        sleep(interval)


def answered(response: httpx2.Response, *statuses: int) -> Any:
    """The body of an answer the step waits for; any other is not there yet."""
    try:
        return ok(response, *statuses)
    except ProductError as exc:
        raise NotYetError(str(exc)) from exc


# ---------------------------------------------------------------- health


def health(context: CheckContext) -> list[str]:
    product = context.product

    def ready() -> dict[str, bool]:
        response = product.internal.get("/ready")
        try:
            checks: dict[str, bool] = dict(response.json().get("checks", {}))
        except ValueError as exc:
            raise NotYetError(f"/ready on the internal listener: {response.status_code}") from exc
        failing = sorted(name for name, up in checks.items() if not up)
        if response.status_code != 200 or failing or not checks:
            failed = ", ".join(failing) or "no checks"
            raise NotYetError(f"/ready on the internal listener is not ready: {failed}")
        return checks

    def public() -> None:
        answered(product.public.get("/health"))

    def worker() -> dict[str, Any]:
        loops = answered(product.worker.get("/loops"))
        running = {name for name, up in loops["loops"].items() if up}
        queues = {name for name, up in loops["task_queues"].items() if up}
        missing = [n for n in (*CONSUMER_GROUPS, *RELAYS, *JOBS) if n not in running]
        missing += [f"task queue {q}" for q in TASK_QUEUES if q not in queues]
        if missing or loops["status"] != "ok":
            raise NotYetError(f"the worker does not run {', '.join(missing) or 'every loop'}")
        loops_health: dict[str, Any] = loops
        return loops_health

    checks = poll(ready, timeout=context.timeout, interval=context.interval)
    poll(public, timeout=context.timeout, interval=context.interval)
    loops = poll(worker, timeout=context.timeout, interval=context.interval)
    groups = [name.split(":", 1)[1] for name in CONSUMER_GROUPS]
    relays = [name.split("/", 1)[0] for name in loops["loops"] if name.endswith("/outbox-relay")]
    return [
        f"internal listener ready: {len(checks)} checks ok",
        "public listener answers /health",
        f"worker: {len(loops['loops'])} loops running, "
        f"heartbeat {loops['heartbeat_age_seconds']} s ago",
        f"consumer groups: {', '.join(groups)}",
        f"outbox relays: {', '.join(relays)}",
        f"task queues: {', '.join(sorted(loops['task_queues']))}",
    ]


# ---------------------------------------------------------------- honesty


def honesty(context: CheckContext) -> list[str]:
    world = load_world(context.golden)
    allowed = set(supported(world))
    calendar = load_calendar(load_ontology())
    published: list[str] = []
    drafts: list[str] = []
    problems: list[str] = []
    for rule in calendar.rules:
        versions = poll(
            partial(rule_versions, context.product, rule.rule_key),
            timeout=context.timeout,
            interval=context.interval,
        )
        for version in versions:
            label = f"{rule.rule_key} v{version['version']}"
            if version["seed_status"] == REVIEWED:
                problems.append(f"{label} is marked reviewed")
            if version["status"] == "published":
                published.append(label)
                if rule.rule_key not in allowed:
                    problems.append(f"{label} is published but world.yaml cites no quote for it")
            elif rule.rule_key not in allowed and version["status"] != "draft":
                problems.append(f"{label} is {version['status']}; it must stay a draft")
        if all(version["status"] == "draft" for version in versions):
            drafts.append(rule.rule_key)
    if world.label_status == REVIEWED or world.reviewed_by:
        problems.append(f"the golden world {world.world_id} is marked reviewed")
    problems += [
        f"golden case {case.case_id} is marked reviewed"
        for case in world.cases.values()
        if case.label_status == REVIEWED
    ]
    if problems:
        raise StepFailedError("; ".join(problems))
    return [
        f"published, all needs_review: {', '.join(published) or 'none yet'}",
        f"drafts: {len(drafts)} of {len(calendar.rules)} seed rules",
        "marked reviewed: none (seed rules, the golden world and its cases)",
    ]


# ---------------------------------------------------------------- the loop


def the_registration(context: CheckContext) -> SeededRegistration:
    def found() -> SeededRegistration:
        seeded = registrations(context.product, BUSINESS_TENANT)
        if not seeded:
            raise NotYetError(f"{BUSINESS_TENANT.name} has no registration: run cw-product seed")
        return seeded[0]

    return poll(found, timeout=context.timeout, interval=context.interval)


def loop(context: CheckContext) -> list[str]:
    product = context.product
    registration = the_registration(context)
    headers = as_tenant(BUSINESS_TENANT.tenant_id)
    expected = registration.business.expected
    versions = {
        str(version["rule_version_id"]): version
        for version in published_in_force(product, today_in_india(context.now()))
        if version["rule_key"] in expected
    }
    if not versions:
        raise StepFailedError(
            "no seed rule the golden world cites is published: run cw-product seed"
        )
    evaluate(product, [BUSINESS_TENANT], now=context.now)

    def decided() -> dict[str, str]:
        results: dict[str, str] = {}
        for version_id, version in versions.items():
            page = answered(
                product.internal.get(
                    f"{ENGINE}/businesses/{registration.registration_id}/decisions",
                    params={"rule_version_id": version_id},
                    headers=headers,
                )
            )
            if not page["items"]:
                raise NotYetError(f"no decision yet for {version['rule_key']}")
            result = str(page["items"][0]["result"])
            if result != expected[version["rule_key"]]:
                raise NotYetError(
                    f"{version['rule_key']} decided {result}, the answers call for "
                    f"{expected[version['rule_key']]}"
                )
            results[str(version["rule_key"])] = result
        return results

    results = poll(decided, timeout=context.timeout, interval=context.interval)
    applying = {vid: v for vid, v in versions.items() if results[v["rule_key"]] == APPLIES}
    if not applying:
        raise StepFailedError("no published rule applies to the business, so nothing can follow")

    def obligations() -> dict[str, list[dict[str, Any]]]:
        listed = answered(
            product.internal.get(
                OBLIGATIONS,
                params={"business_id": registration.registration_id},
                headers=headers,
            )
        )
        found = {vid: [o for o in listed if o["rule_version_id"] == vid] for vid in applying}
        waiting = [applying[vid]["rule_key"] for vid, items in found.items() if not items]
        if waiting:
            raise NotYetError(f"no obligation yet for {', '.join(waiting)}")
        return found

    made = poll(obligations, timeout=context.timeout, interval=context.interval)
    cited: dict[str, int] = {}
    for version_id, version in applying.items():
        citations = ok(product.internal.get(f"{RULEBOOK}/rule-versions/{version_id}/citations"))
        verified = [citation for citation in citations if citation["verified"]]
        if not verified:
            raise StepFailedError(
                f"{version['rule_key']} has obligations but cites no verified clause"
            )
        cited[str(version["rule_key"])] = len(verified)

    def change_card() -> tuple[dict[str, Any], list[dict[str, Any]]]:
        page = answered(
            product.internal.get(
                NOTIFICATIONS,
                params={"business_id": registration.registration_id, "limit": 100},
                headers=headers,
            )
        )
        cards = [n for n in page["items"] if n["occasion"] == CHANGE_CARD]
        through_sink = [
            card
            for card in cards
            if card["state"] in SENT_STATES
            and str(card["provider_message_id"]).startswith(MESSAGE_ID_PREFIX)
        ]
        if not through_sink:
            states = ", ".join(f"{c['channel']} {c['state']}" for c in cards) or "none queued"
            raise NotYetError(f"no change card sent through the sink yet ({states})")
        return through_sink[0], cards

    card, cards = poll(change_card, timeout=context.timeout, interval=context.interval)
    lines = [
        "decisions: " + ", ".join(f"{key} {result}" for key, result in sorted(results.items())),
        "obligations: "
        + ", ".join(
            f"{applying[vid]['rule_key']} {len(items)} ({cited[applying[vid]['rule_key']]} "
            "verified citations)"
            for vid, items in made.items()
        ),
        f"change card: {card['channel']} {card['state']} through the sink "
        f"({card['provider_message_id']})",
    ]
    lines += [
        f"also: {other['channel']} {other['state']}: {other['error']}"
        for other in cards
        if other is not card and other["error"]
    ]
    lines.append(sink_line(product.sink_path, str(card["provider_message_id"])))
    return lines


def sink_line(path: Path, message_id: str) -> str:
    """Where the sink recorded the message; a line the step reports, or ``StepFailedError`` when
    the file is here and lacks it."""
    if not path.is_file():
        return f"sink file {path} is not on this machine; the notification's id says sink"
    for raw in path.read_text(encoding="utf-8").splitlines():
        if json.loads(raw).get("provider_message_id") == message_id:
            return f"sink file {path} holds the message"
    raise StepFailedError(f"the sink file {path} has no line for {message_id}")


# ---------------------------------------------------------------- isolation


def isolation(context: CheckContext) -> list[str]:
    product = context.product
    lines: list[str] = []
    seen = {
        tenant.key: poll(
            partial(_seeded, product, tenant),
            timeout=context.timeout,
            interval=context.interval,
        )
        for tenant in (BUSINESS_TENANT, CA_FIRM_TENANT)
    }
    for owner, reader in ((BUSINESS_TENANT, CA_FIRM_TENANT), (CA_FIRM_TENANT, BUSINESS_TENANT)):
        own = _holdings(product, owner.tenant_id, seen[owner.key])
        if owner is BUSINESS_TENANT and not own.decisions:
            raise StepFailedError(f"{owner.name} has no decision to hide: run the loop step first")
        theirs = _holdings(product, reader.tenant_id, seen[owner.key])
        if theirs.any():
            raise StepFailedError(f"{reader.name} reads {theirs.describe()} of {owner.name}")
        for decision_id in own.decision_ids[:1]:
            hidden = product.internal.get(
                f"{ENGINE}/decisions/{decision_id}", headers=as_tenant(reader.tenant_id)
            )
            if hidden.status_code != 404:
                raise StepFailedError(f"{reader.name} reads {owner.name}'s decision {decision_id}")
        for business_id in {r.entity_id for r in seen[owner.key]}:
            business = product.internal.get(
                f"/v1/businesses/{business_id}", headers=as_tenant(reader.tenant_id)
            )
            if business.status_code != 404:
                raise StepFailedError(f"{reader.name} reads {owner.name}'s business {business_id}")
        lines.append(f"{reader.name} reads none of {owner.name}'s {own.describe()}")
    return lines


@dataclass(frozen=True, slots=True)
class Holdings:
    """What one tenant reads of a set of registrations."""

    decision_ids: list[str]
    obligations: int
    notifications: int

    @property
    def decisions(self) -> int:
        return len(self.decision_ids)

    def any(self) -> bool:
        return bool(self.decision_ids or self.obligations or self.notifications)

    def describe(self) -> str:
        return (
            f"{self.decisions} decisions, {self.obligations} obligations and "
            f"{self.notifications} notifications"
        )


def _seeded(product: Product, tenant: SyntheticTenant) -> list[SeededRegistration]:
    seeded = registrations(product, tenant)
    if len(seeded) != len(tenant.businesses):
        raise NotYetError(f"{tenant.name} is not seeded: run cw-product seed")
    return seeded


def _holdings(product: Product, reader: UUID, seeded: Iterable[SeededRegistration]) -> Holdings:
    headers = as_tenant(reader)
    decisions: list[str] = []
    obligations = notifications = 0
    for registration in seeded:
        business = registration.registration_id
        page = ok(
            product.internal.get(f"{ENGINE}/businesses/{business}/decisions", headers=headers)
        )
        decisions += [str(item["decision_id"]) for item in page["items"]]
        obligations += len(
            ok(product.internal.get(OBLIGATIONS, params={"business_id": business}, headers=headers))
        )
        listed = ok(
            product.internal.get(NOTIFICATIONS, params={"business_id": business}, headers=headers)
        )
        notifications += len(listed["items"])
    return Holdings(decisions, obligations, notifications)


# ---------------------------------------------------------------- the command

STEPS: list[Step] = [
    Step("health", "both listeners and every worker loop are up", health),
    Step("honesty", "only cited seed rules are published, all still needs_review", honesty),
    Step("loop", "a published rule becomes decisions, obligations and a change card", loop),
    Step("isolation", "neither synthetic tenant reads the other's records", isolation),
]
"""The steps in the order they run. A later package appends its own."""


def run_checks(
    context: CheckContext,
    steps: Sequence[Step] | None = None,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> list[StepResult]:
    results: list[StepResult] = []
    for step in STEPS if steps is None else steps:
        started = clock()
        result = StepResult(step.name, step.summary, ok=True, seconds=0.0)
        try:
            result.details = step.run(context)
        except (StepFailedError, ProductError) as exc:
            result.ok, result.error = False, str(exc)
        except Exception as exc:
            # An answer the step did not expect (a connection refused, a body of another shape)
            # fails this step, and the next ones still run.
            result.ok, result.error = False, f"{type(exc).__name__}: {exc}"
        result.seconds = round(clock() - started, 1)
        results.append(result)
    return results


def select(names: Sequence[str] | None, steps: Sequence[Step] | None = None) -> list[Step]:
    """The steps named, in the check's order; every step when none is named."""
    available = list(STEPS if steps is None else steps)
    if not names:
        return available
    unknown = sorted(set(names) - {step.name for step in available})
    if unknown:
        raise ProductError(
            f"no step {', '.join(unknown)}; the steps are "
            f"{', '.join(step.name for step in available)}"
        )
    return [step for step in available if step.name in names]


def render(results: Sequence[StepResult]) -> str:
    passed = sum(result.ok for result in results)
    lines = ["# cw-product check", ""]
    for result in results:
        mark = "ok    " if result.ok else "FAILED"
        lines.append(f"{mark}  {result.name:<10} {result.seconds:>5.1f} s  {result.summary}")
        lines += [f"        - {detail}" for detail in result.details]
        if result.error:
            lines.append(f"        error: {result.error}")
    lines += ["", f"{passed} of {len(results)} steps passed."]
    return "\n".join(lines) + "\n"


def as_json(results: Sequence[StepResult]) -> Mapping[str, Any]:
    return {
        "ok": all(result.ok for result in results),
        "steps": [
            {
                "name": result.name,
                "summary": result.summary,
                "ok": result.ok,
                "seconds": result.seconds,
                "details": result.details,
                "error": result.error,
            }
            for result in results
        ],
    }
