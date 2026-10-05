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
- ``recompute``: a new synthetic business in the business tenant, made through the profile's
  business API (``POST /v1/businesses``), gets its decisions from profile.updated alone (the
  engine's consumer, never ``evaluate``) and the obligations of the rule that applies; then a
  changed answer (``PATCH /v1/businesses/{id}``, the registration moves to the quarterly scheme)
  brings a new decision that the monthly rule does not apply and closes its obligations with
  ``profile_changed``, while the quarterly rule of its state gets obligations when it is
  published. Every decision of the business has the trigger profile_updated, and no review item
  opens for it (none of the seed rules has a free-text predicate; unsure for an unanswered
  question opens none). Each run makes a new business, named with the time it was made, since a
  closed obligation stays closed and only a new business shows the whole change again.
- ``fanout``: the rule.published fan-out. While gstr9_annual is not published yet it sets the
  global hold through the engine's route, publishes gstr9_annual (``cw-product publish --rule
  gstr9_annual``), waits for the run to stand held with nothing decided, releases the hold and
  waits for the run to complete. Once it is published (a second check on the same database) it
  finds that run completed instead, resuming it if an earlier check left it paused, and sets and
  releases the hold again with nothing to stop. Either way the run's counters match the directory
  entries of the level, each synthetic registration the directory listed has its decision from
  the fan-out (trigger rule_published) with the result its answers call for, the registrations
  GSTR-9 applies to in both synthetic tenants have their GSTR-9 obligations, and ``audit.event``
  holds the hold, the release and any resume this step made. The directory and the audit rows of
  no tenant are read through ``records.PostgresRecords`` (``CW_PRODUCT_RECORDS_URL``, read only).
  A hold an interrupted check left is lifted first; anyone else's makes the step fail.
"""

import json
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import httpx2

from cw_demo.product.client import GOLDEN, Product, ProductError, as_tenant, ok
from cw_demo.product.evaluate import (
    SeededRegistration,
    evaluate,
    published_in_force,
    registrations,
    today_in_india,
)
from cw_demo.product.publish import RULEBOOK, publish, rule_versions, supported
from cw_demo.product.records import ProductRecords
from cw_demo.product.tenants import (
    APPLIES,
    BUSINESS_TENANT,
    CA_FIRM_TENANT,
    NOT_APPLICABLE,
    TENANTS,
    SyntheticTenant,
)
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
    "applicability-engine/consumer:applicability-engine.profiles",
    "applicability-engine/consumer:applicability-engine.rules",
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
TASK_QUEUES: Final = ("applicability", "pipeline")
REVIEWED: Final = "reviewed"
BUSINESSES: Final = "/v1/businesses"
REVIEW_ITEMS: Final = f"{ENGINE}/review-items"
MONTHLY: Final = "gstr3b_monthly"
QUARTERLY: Final = "gstr3b_quarterly_group_a"
"""The quarterly GSTR-3B rule of the probe's state (Karnataka, 29)."""
PROFILE_UPDATED: Final = "profile_updated"
CLOSED: Final = "closed_not_applicable"
PROFILE_CHANGED: Final = "profile_changed"
PROBE_ANSWERS: Final[tuple[tuple[str, object], ...]] = (
    ("state_codes", ["29"]),
    ("registration_type", "regular"),
    ("filing_scheme", "regular_monthly"),
    ("return_filing_frequency", "monthly"),
)
"""A monthly GSTR-3B filer in Karnataka: the entity's state and the registration's answers (a
GSTIN no lookup knows pre-fills nothing, so the registration type is answered too)."""
PROBE_FLIP: Final[tuple[tuple[str, object], ...]] = (
    ("filing_scheme", "regular_qrmp"),
    ("return_filing_frequency", "quarterly"),
)
"""The change the check makes: the registration moves to the quarterly scheme (QRMP)."""
FAN_OUTS: Final = f"{ENGINE}/fan-outs"
FAN_OUT_HOLD: Final = f"{ENGINE}/fan-out-hold"
GSTR9: Final = "gstr9_annual"
FAN_OUT_LEVEL: Final = "registration"
"""The level of gstr9_annual, whose directory entries its fan-out decides."""
RULE_PUBLISHED: Final = "rule_published"
CHECK_MARK: Final = "cw-product check"
"""How a hold or a resume of this step starts its reason, so a later check knows its own."""
HOLD_ACTION: Final = "applicability.fanout.hold"
RELEASE_ACTION: Final = "applicability.fanout.release"
RESUME_ACTION: Final = "applicability.fanout.resume"


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
    records: ProductRecords | None = None
    """The directory and the audit log, read where no route serves them (the fanout step)."""


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


# ---------------------------------------------------------------- recompute


@dataclass(frozen=True, slots=True)
class Probe:
    """The business the recompute step makes: its name, GSTIN, entity and registration."""

    name: str
    gstin: str
    entity_id: str
    registration_id: str


def probe_gstin(token: int) -> str:
    """A GSTIN of Karnataka that no lookup knows: the PAN ZZZ<two letters><four digits>Z, like
    the made-up Delhi one of the CA firm's client."""
    letters = chr(ord("A") + token % 26) + chr(ord("A") + token // 26 % 26)
    digits = token // 676 % 10_000
    return f"29ZZZ{letters}{digits:04d}Z1Z5"


def make_probe(context: CheckContext, headers: Mapping[str, str]) -> Probe:
    """A new business in the business tenant, through the profile's business API."""
    stamp = context.now().astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    answers = [{"key": key, "value": value} for key, value in PROBE_ANSWERS]
    for _ in range(3):
        gstin = probe_gstin(uuid4().int)
        name = f"Recompute probe {stamp} (synthetic)"
        body = {"name": name, "gstin": gstin, "registration_name": name, "answers": answers}
        created = ok(
            context.product.internal.post(
                BUSINESSES, json=body, headers={**headers, "Idempotency-Key": str(uuid4())}
            ),
            201,
        )
        if created["created"]:
            business = created["business"]
            (registration,) = business["registrations"]
            return Probe(name, gstin, str(business["id"]), str(registration["id"]))
    raise StepFailedError("three made-up GSTINs in a row were taken; run the check again")


def recompute(context: CheckContext) -> list[str]:
    product = context.product
    headers = as_tenant(BUSINESS_TENANT.tenant_id)
    versions = {
        str(version["rule_key"]): str(version["rule_version_id"])
        for version in published_in_force(product, today_in_india(context.now()))
    }
    if MONTHLY not in versions:
        raise StepFailedError(f"{MONTHLY} is not published: run cw-product seed")
    monthly, quarterly = versions[MONTHLY], versions.get(QUARTERLY)
    probe = make_probe(context, headers)
    wait = partial(poll, timeout=context.timeout, interval=context.interval)

    def decision_of(version_id: str, result: str, after: str | None = None) -> dict[str, Any]:
        page = answered(
            product.internal.get(
                f"{ENGINE}/businesses/{probe.registration_id}/decisions",
                params={"rule_version_id": version_id, "limit": 1},
                headers=headers,
            )
        )
        if not page["items"]:
            raise NotYetError(f"no decision of {MONTHLY} yet for {probe.name}")
        latest: dict[str, Any] = page["items"][0]
        if latest["decision_id"] == after or (latest["result"], latest["trigger"]) != (
            result,
            PROFILE_UPDATED,
        ):
            raise NotYetError(
                f"the latest decision of {MONTHLY} is {latest['result']} "
                f"({latest['trigger']}); waiting for {result} from profile.updated"
            )
        return latest

    def obligations_of(version_id: str) -> list[dict[str, Any]]:
        listed: list[dict[str, Any]] = answered(
            product.internal.get(
                OBLIGATIONS,
                params={"business_id": probe.registration_id, "rule_version_id": version_id},
                headers=headers,
            )
        )
        return listed

    def opened() -> list[dict[str, Any]]:
        made = obligations_of(monthly)
        if not made or any(o["status"] == CLOSED for o in made):
            raise NotYetError(f"no open obligation of {MONTHLY} yet for {probe.name}")
        return made

    def closed() -> list[dict[str, Any]]:
        made = obligations_of(monthly)
        still = [o for o in made if (o["status"], o["closed_reason"]) != (CLOSED, PROFILE_CHANGED)]
        if still:
            raise NotYetError(f"{len(still)} obligations of {MONTHLY} are not closed yet")
        return made

    def quarterly_made() -> list[dict[str, Any]]:
        made = obligations_of(quarterly or "")
        if not made:
            raise NotYetError(f"no obligation of {QUARTERLY} yet for {probe.name}")
        return made

    first = wait(partial(decision_of, monthly, APPLIES))
    made = wait(opened)
    ok(
        product.internal.patch(
            f"{BUSINESSES}/{probe.entity_id}",
            json={
                "changes": [
                    {"key": key, "value": value, "node_id": probe.registration_id}
                    for key, value in PROBE_FLIP
                ]
            },
            headers=headers,
        )
    )
    flipped = wait(partial(decision_of, monthly, NOT_APPLICABLE, first["decision_id"]))
    closed_ones = wait(closed)
    lines = [
        f"probe: {probe.name}, {probe.gstin}, registration {probe.registration_id}, "
        "made with POST /v1/businesses",
        f"profile.updated decided {MONTHLY} {first['result']} ({first['decision_id']}); "
        f"{len(made)} obligations made",
        f"after PATCH to the quarterly scheme: {MONTHLY} {flipped['result']} "
        f"({flipped['decision_id']}); {len(closed_ones)} obligations closed ({PROFILE_CHANGED})",
    ]
    if quarterly is not None:
        lines.append(f"{QUARTERLY}: {len(wait(quarterly_made))} obligations made")
    every = answered(
        product.internal.get(
            f"{ENGINE}/businesses/{probe.registration_id}/decisions",
            params={"limit": 200},
            headers=headers,
        )
    )["items"]
    triggers = sorted({str(item["trigger"]) for item in every})
    if triggers != [PROFILE_UPDATED]:
        raise StepFailedError(f"the probe's decisions have the triggers {triggers}")
    items = answered(product.internal.get(REVIEW_ITEMS, params={"limit": 200}, headers=headers))[
        "items"
    ]
    mine = [item for item in items if item["business_id"] == probe.registration_id]
    if mine:
        raise StepFailedError(f"{len(mine)} review items opened for {probe.name}")
    lines.append(
        f"{len(every)} decisions, every one from profile.updated; no review item for the probe"
    )
    return lines


# ---------------------------------------------------------------- fanout


def fanout(context: CheckContext) -> list[str]:
    records = context.records
    if records is None:
        raise StepFailedError(
            "the fanout step reads the business directory and audit.event: set "
            "CW_PRODUCT_RECORDS_URL (make product-check passes it)"
        )
    product = context.product
    since = context.now()
    lines = lift_own_hold(product)
    versions = rule_versions(product, GSTR9)
    if not versions:
        raise StepFailedError(f"{GSTR9} has no version: run make seed SERVICE=rulebook")
    if versions[-1]["status"] != "published":
        run, published = publish_behind_the_hold(context, records)
        lines += published
    else:
        run, verified = completed_run(context, str(versions[-1]["rule_version_id"]))
        lines += verified
    lines += counted(run, records)
    lines += decided(context, run, records)
    lines += audited(records, since)
    return lines


def hold(product: Product, held: bool, reason: str) -> dict[str, Any]:
    body: dict[str, Any] = ok(
        product.internal.put(FAN_OUT_HOLD, json={"held": held, "reason": reason})
    )
    return body


def lift_own_hold(product: Product) -> list[str]:
    """Release a hold an interrupted check left; refuse to go on under anyone else's."""
    current = ok(product.internal.get(FAN_OUT_HOLD))
    if not current["held"]:
        return []
    if not str(current["reason"]).startswith(CHECK_MARK):
        raise StepFailedError(
            f"the fan-out hold is set ({current['reason']!r}, by {current['set_by']}); the check "
            "does not lift a hold it did not set"
        )
    hold(product, False, f"{CHECK_MARK}: lifting the hold an interrupted check left")
    return ["lifted the hold an interrupted check left"]


def fan_out_of(product: Product, rule_version_id: str) -> dict[str, Any]:
    run: dict[str, Any] = answered(product.internal.get(f"{FAN_OUTS}/{rule_version_id}"))
    return run


def wait_for_status(context: CheckContext, rule_version_id: str, *wanted: str) -> dict[str, Any]:
    def reached() -> dict[str, Any]:
        run = fan_out_of(context.product, rule_version_id)
        if run["status"] == "disabled":
            raise StepFailedError(
                f"the fan-out of {GSTR9} is disabled: the worker runs with the flag "
                "applicability.fanout off (CW_APPLICABILITY_FANOUT_ENABLED)"
            )
        if run["status"] in ("cancelled", "failed"):
            raise StepFailedError(
                f"the fan-out of {GSTR9} is {run['status']}: {run['status_reason']} "
                f"{run['last_error']}".rstrip()
            )
        if run["status"] not in wanted:
            raise NotYetError(
                f"the fan-out of {GSTR9} is {run['status']}, not {' or '.join(wanted)}"
            )
        return run

    return poll(reached, timeout=context.timeout, interval=context.interval)


def publish_behind_the_hold(
    context: CheckContext, records: ProductRecords
) -> tuple[dict[str, Any], list[str]]:
    """Hold, publish gstr9_annual, see the run held with nothing decided, release, see it
    complete."""
    product = context.product
    stamp = context.now().astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    hold(product, True, f"{CHECK_MARK} {stamp}: held before the GSTR-9 publication (synthetic)")
    try:
        (rule,) = publish(product, [GSTR9], golden=context.golden).rules
        held = wait_for_status(context, rule.rule_version_id, "held")
        time.sleep(max(2 * context.interval, 0.5))
        still = fan_out_of(product, rule.rule_version_id)
        if (still["status"], still["evaluated"]) != ("held", 0):
            raise StepFailedError(
                f"the held run moved on: {still['status']}, {still['evaluated']} decided"
            )
        early = published_decisions(context, rule.rule_version_id)
        if early:
            raise StepFailedError(f"{len(early)} decisions came from the fan-out while it was held")
    finally:
        hold(product, False, f"{CHECK_MARK} {stamp}: released after seeing the run held")
    run = wait_for_status(context, rule.rule_version_id, "completed")
    return run, [
        f"hold set, {GSTR9} v{rule.version} published ({rule.rule_version_id}): the run stood "
        f"{held['status']} with {held['evaluated']} of {held['businesses_total']} decided and "
        "no decision from it",
        f"hold released: the run {run['status']}",
    ]


def completed_run(context: CheckContext, rule_version_id: str) -> tuple[dict[str, Any], list[str]]:
    """The fan-out of a gstr9_annual an earlier check published: completed, resumed first when
    it was left paused; the hold set and released again, with nothing to stop."""
    product = context.product
    response = product.internal.get(f"{FAN_OUTS}/{rule_version_id}")
    if response.status_code == 404:
        raise StepFailedError(
            f"{GSTR9} is published but has no fan-out: it was published before the worker "
            "consumed rule.published (make product-logs PROC=worker)"
        )
    run: dict[str, Any] = ok(response)
    lines = [f"{GSTR9} was published before ({rule_version_id}): its fan-out is {run['status']}"]
    if run["status"] == "paused":
        ok(
            product.internal.post(
                f"{FAN_OUTS}/{rule_version_id}/resume",
                json={"reason": f"{CHECK_MARK}: resuming the run an earlier check left paused"},
            )
        )
        lines.append("resumed the run an earlier check left paused")
    run = wait_for_status(context, rule_version_id, "completed")
    stamp = context.now().astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    held = hold(product, True, f"{CHECK_MARK} {stamp}: hold with no fan-out to stop (synthetic)")
    try:
        if not held["held"] or not str(held["reason"]).startswith(CHECK_MARK):
            raise StepFailedError(f"the hold reads {held} after it was set")
    finally:
        released = hold(product, False, f"{CHECK_MARK} {stamp}: released again")
    if released["held"]:
        raise StepFailedError("the hold is still set after it was released")
    lines.append("hold set and released again; the completed run stays completed")
    return run, lines


def counted(run: dict[str, Any], records: ProductRecords) -> list[str]:
    finished = datetime.fromisoformat(str(run["finished_at"]))
    listed = records.directory_count(FAN_OUT_LEVEL, as_of=finished)
    counts = (run["businesses_total"], run["evaluated"])
    if counts != (listed, listed):
        raise StepFailedError(
            f"the run counted {run['businesses_total']} businesses and decided "
            f"{run['evaluated']}, but the directory listed {listed} of level {FAN_OUT_LEVEL}"
        )
    if (run["flips_compared"], run["flips"]) != (0, 0):
        raise StepFailedError(f"{GSTR9} supersedes nothing, yet the run compared flips")
    return [
        f"counters: {run['evaluated']} of {run['businesses_total']} decided, {run['applies']} "
        f"apply, matching the {listed} directory entries of level {FAN_OUT_LEVEL}"
    ]


def published_decisions(context: CheckContext, rule_version_id: str) -> list[dict[str, Any]]:
    """The fan-out's decisions of the version for the synthetic registrations."""
    found: list[dict[str, Any]] = []
    for tenant in TENANTS:
        for seeded in registrations(context.product, tenant):
            found += [
                item
                for item in decisions_of(context, tenant, seeded, rule_version_id)
                if item["trigger"] == RULE_PUBLISHED
            ]
    return found


def decisions_of(
    context: CheckContext, tenant: SyntheticTenant, seeded: SeededRegistration, version_id: str
) -> list[dict[str, Any]]:
    page = ok(
        context.product.internal.get(
            f"{ENGINE}/businesses/{seeded.registration_id}/decisions",
            params={"rule_version_id": version_id, "limit": 200},
            headers=as_tenant(tenant.tenant_id),
        )
    )
    items: list[dict[str, Any]] = page["items"]
    return items


def decided(context: CheckContext, run: dict[str, Any], records: ProductRecords) -> list[str]:
    """Each listed synthetic registration's decision from the fan-out, and the GSTR-9
    obligations of those it applies to, in both tenants."""
    version_id = str(run["rule_version_id"])
    finished = datetime.fromisoformat(str(run["finished_at"]))
    lines: list[str] = []
    applying: dict[str, list[tuple[SyntheticTenant, SeededRegistration]]] = {}
    for tenant in TENANTS:
        seeded = registrations(context.product, tenant)
        listed = records.listed([s.registration_id for s in seeded], as_of=finished)
        for registration in seeded:
            if registration.registration_id not in listed:
                lines.append(f"{registration.business.key}: not in the directory, not fanned out")
                continue
            fanned = [
                item
                for item in decisions_of(context, tenant, registration, version_id)
                if item["trigger"] == RULE_PUBLISHED
            ]
            expected = registration.business.expected[GSTR9]
            if not fanned:
                raise StepFailedError(
                    f"{registration.business.key} is in the directory but has no {GSTR9} "
                    "decision from the fan-out"
                )
            if fanned[0]["result"] != expected:
                raise StepFailedError(
                    f"the fan-out decided {GSTR9} {fanned[0]['result']} for "
                    f"{registration.business.key}; its answers call for {expected}"
                )
            lines.append(f"{registration.business.key}: {GSTR9} {expected} from the fan-out")
            if expected == APPLIES:
                applying.setdefault(tenant.key, []).append((tenant, registration))
    missing = [tenant.name for tenant in TENANTS if tenant.key not in applying]
    if missing:
        raise StepFailedError(
            f"{GSTR9} applies to no registration the directory lists in {', '.join(missing)}: "
            "run make product-seed"
        )
    for found in applying.values():
        for tenant, registration in found:
            made = poll(
                partial(gstr9_obligations, context, tenant, registration, version_id),
                timeout=context.timeout,
                interval=context.interval,
            )
            lines.append(
                f"{tenant.name}, {registration.business.name}: {len(made)} GSTR-9 obligations"
            )
    return lines


def gstr9_obligations(
    context: CheckContext,
    tenant: SyntheticTenant,
    registration: SeededRegistration,
    version_id: str,
) -> list[dict[str, Any]]:
    listed: list[dict[str, Any]] = answered(
        context.product.internal.get(
            OBLIGATIONS,
            params={"business_id": registration.registration_id, "rule_version_id": version_id},
            headers=as_tenant(tenant.tenant_id),
        )
    )
    if not listed:
        raise NotYetError(f"no GSTR-9 obligation yet for {registration.business.name}")
    return listed


def audited(records: ProductRecords, since: datetime) -> list[str]:
    """The audit rows of the hold, the release and any resume this step made."""
    rows = [
        row
        for row in records.audit_entries(
            actions=(HOLD_ACTION, RELEASE_ACTION, RESUME_ACTION), since=since
        )
        if row.reason.startswith(CHECK_MARK)
    ]
    actions = [row.action for row in rows]
    for wanted in (HOLD_ACTION, RELEASE_ACTION):
        if wanted not in actions:
            raise StepFailedError(f"audit.event has no {wanted} row from this check")
    if any(row.tenant_id is not None for row in rows):
        raise StepFailedError("a fan-out control was audited as one tenant's")
    resumes = actions.count(RESUME_ACTION)
    actors = sorted({row.actor_label for row in rows})
    return [
        f"audit.event: {actions.count(HOLD_ACTION)} hold, {actions.count(RELEASE_ACTION)} "
        f"release and {resumes} resume rows of no tenant, by {', '.join(actors)}"
    ]


# ---------------------------------------------------------------- the command

STEPS: list[Step] = [
    Step("health", "both listeners and every worker loop are up", health),
    Step("honesty", "only cited seed rules are published, all still needs_review", honesty),
    Step("loop", "a published rule becomes decisions, obligations and a change card", loop),
    Step("isolation", "neither synthetic tenant reads the other's records", isolation),
    Step(
        "recompute",
        "a business made or changed in the profile gets decisions and obligations by itself",
        recompute,
    ),
    Step(
        "fanout",
        "a rule published behind the hold fans out to every business once it is released",
        fanout,
    ),
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
