"""``cw-product check``: prove that the running product works, one named step after another.

``STEPS`` is the ordered list the check runs; a later package appends its own ``Step`` (engine
recompute on profile.updated, fan-out on rule.published, obligation tracking, the changes feed,
rollback) and the command runs it after these. A step returns the lines it reports and raises
``StepFailedError`` with what is wrong. Whatever it waits for it polls with ``poll``, up to the
check's timeout (``TIMEOUT_SECONDS``, about 30 s), since the worker gets there a few seconds after
the API answers. One failed step does not stop the next.

- ``health``: the internal listener's ``/ready`` has every service's checks ok, the public
  listener answers ``/health``, and the worker's ``/loops`` lists the consumer groups, outbox
  relays, periodic jobs and Temporal task queue the chain needs, each of them running, and the
  pipeline's relay, which publishes document.discovered.
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
- ``reminders``: ``obligation-sweep --once --now <moment> --tenant <business tenant>`` runs the
  reminder sweep (and the rolling window) as of a few days before one of the business tenant's
  open obligations is due, and its ``obligation.due_soon`` reaches the sink as a reminder about
  that obligation. The moment is the obligation's due date less 5 days, 2 days or 12 hours, the
  first one whose threshold (7, 3, 1 days) has not reminded it yet, so a later check on the same
  database still sees a new reminder; the sweep touches no tenant but the business tenant.
- ``rollback``: destructive, so it runs only with ``--destructive`` (the CI dev-stack job passes
  it; it starts from a fresh database) and reports itself skipped otherwise. It withdraws
  gstr9_annual through the rulebook's withdraw route as the first synthetic reviewer, then waits
  for every GSTR-9 obligation of the registrations it applies to, in both synthetic tenants, to
  close with ``rule_withdrawn``, and for the withdrawal notices: sent through the sink for the
  business tenant, and queued for the CA firm's daily digest (or sent, once the digest went). On
  a database where it was withdrawn already, it checks what followed. Never run it against a
  database whose seed rules others rely on: only four seed rules can be published at all.
- ``tracking``: a new synthetic business in the business tenant (``POST /v1/businesses``, a
  monthly GSTR-3B filer) gets its obligations of the monthly rule from profile.updated. The first
  one due must be the return it files next from the day it was decided, which is the previous
  month's while that is still due (September's, due 20 October, when decided on 6 October;
  ``Recurrence.periods_due``). The step starts it, assigns it to the tenant's synthetic owner, and
  completes it twice with one Idempotency-Key: one closure, and the second answer is the first,
  replayed. The detail then shows the history (created, started, assigned, closed), the rule
  version's reviewed-by data naming both synthetic reviewers while its seed status stays
  needs_review, and verified citations; a comment is added and listed. Each run spends a business
  of its own, so the seeded registration's obligations stay for the reminders step and a later
  check passes again.
- ``changes``: the version of gstr9_annual the fanout step published. ``GET /v1/changes`` lists its
  publication (read from its ``published_at`` on) with both synthetic reviewers as its approvers,
  the seed status needs_review and verified citations. ``GET /v1/changes/{id}/impact`` as the CA
  firm, with ``result=applies``, lists exactly the firm's registrations the answers call for under
  the client they belong to, and the version's fan-out completed. A dry run of the version scoped
  to the CA firm (``POST /v1/applicability-engine/dry-runs``) counts what the firm's latest
  decisions of the version count for the registrations the directory lists (the ones a fan-out
  decides; a database whose consumer group began after a registration was made may lack it), with
  every one decided and none skipped; it wrote one ``applicability.dry_run`` row of no tenant,
  found by the request's correlation id, and not one decision, review item or outbox row of the
  firm (counted before and after through ``records.PostgresRecords``). On a database where the
  rollback step withdrew the version, the publication is still in the feed and the dry run reads
  the withdrawn version.
- ``public``: the public API through the public listener. As the business tenant,
  ``GET /v1/businesses/{id}/obligations`` lists the seeded registration's obligations by due date,
  pages of one follow one another, each item carries its rule's title, ``status`` keeps what it
  names, a window of 367 days is a 422, and the CA firm reading it gets a 404. ``POST /v1/qa``
  asks "When is my GSTR-3B due?": with the knowledge graph off the structured layer answers it from
  the obligations, naming the earliest open GSTR-3B obligation due from today that the public
  listing holds just before the question, with verified citations (both are read again if a
  decision changes the listing meanwhile); the CA firm asking about the registration gets a 404.
  As the CA firm, ``POST /v1/notification/bulk`` sends the change card of gstr9_annual (of the
  quarterly return of the client's state once a rollback check withdrew it) to the clients its
  impact lists: a synthetic client contact made for the step (an owner who follows those clients,
  on an ``.invalid`` mailbox) gets one card per client, the firm's own admin none; the same
  Idempotency-Key answers the same, and a new key finds every card queued already. Each request
  that ran wrote one ``notification.bulk`` row of the firm (found by its correlation id through
  ``records``), the contact's card goes out through the sink, and the contact is removed afterwards
  (with any an interrupted check left). A service-to-service route, ``POST /v1/notification/send``,
  answers 404 on the public listener.
- ``sources``: the pipeline's source manager on the internal listener. Every built-in source is
  listed with its name, regulator, cadence, status and freshness (any other source the database
  holds is counted, not judged). The product never fetches a
  live regulator site, so crawling stays off (``make product`` passes
  ``CW_PIPELINE_CRAWL_ENABLED=false``) and no source of the product is pointed at recorded
  fixtures: the step proves the refusal instead. A fetch of a key no source has must be refused
  as crawling off (with crawling on it would be a 404, and the step stops there without touching
  a real source); then a fetch of ``cbic_notifications`` must be refused the same way and record
  no crawl run. The public listener answers the list 404 in header mode. A crawl over recorded
  fixtures runs in ``tools/demo/tests/unit/test_pipeline_crawl_flow.py`` and the pipeline's
  crawl workflow tests instead. The statutes (``cgst_act``, ``cgst_rules``, ``igst_act``) must
  read upload-only, the task queue (``GET /v1/pipeline/tasks``) must answer, and an upload of a
  file that is no document must be refused 415 with nothing stored: a stored document is never
  deleted, so the check uploads none (``tools/demo/tests/unit/test_manual_parse_flow.py`` runs
  uploads and a manual parse).
- ``review``: the rulebook's review tasks on the internal listener. ``POST
  /v1/rulebook/review/tasks/seed`` opens a task for every seed draft that has none waiting, and a
  second request opens nothing; every seed draft that needs review then has a task waiting
  (open or claimed); a task waiting on a version the publish routes moved on (``cw-product
  publish`` publishes seed rules outside the review flow) is reported, not judged. The step claims
  one task as the synthetic check analyst (``analysts.CHECK_ANALYST``): the one it holds from an
  earlier run, or the first open one in the queue whose version is a draft; claiming it again
  changes nothing. It reads that task (its draft, the specification described, the citations
  with their verification, the history) and the stats, which count the waiting tasks. The
  public listener answers the queue 404 in header mode. Nothing is edited or decided, so no seed
  draft changes, none is approved or published and none is marked reviewed:
  ``tools/demo/tests/unit/test_review_flow.py`` edits, approves and publishes on memory stores.
- ``extraction``: the pipeline's triage and its rule extraction, ingesting nothing. It runs only
  while the product's gateway answers from its fake model (``CW_LLM_PROVIDER=fake``, the
  default), deterministic and free, and reports itself skipped otherwise: the check never asks
  a real model. ``GET /v1/pipeline/tasks?kind=triage`` answers with triage tasks only; a triage
  of a task id nobody opened is refused 404 ``pipeline-task-not-found`` and a relevant one
  without a type 422, so no task changes. The extraction's stage, as the worker builds it, asks
  the product's gateway with the registered prompt ``extraction.rule_candidate@1`` about a
  synthetic notification that is stored nowhere: the gateway accepts the prompt (its digest is
  the registry's) and the fake model's placeholder, which cites no clause, is read as no
  candidate twice. Nothing is stored or published; a gateway ledger row records each ask.
  ``tools/demo/tests/unit/test_extraction_flow.py`` extracts from a recorded notification.
"""

import io
import json
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import httpx2

from cw_demo.product.analysts import CHECK_ANALYST, FIRST_REVIEWER, NOTE, REVIEWERS
from cw_demo.product.client import (
    GOLDEN,
    Product,
    ProductError,
    as_tenant,
    describe,
    ok,
    problem_slug,
)
from cw_demo.product.evaluate import (
    IDEMPOTENCY_HEADER,
    IST,
    REPLAYED_HEADER,
    SeededRegistration,
    evaluate,
    published_in_force,
    registrations,
    today_in_india,
)
from cw_demo.product.publish import RULEBOOK, publish, rule_versions, supported
from cw_demo.product.records import ProductRecords
from cw_demo.product.seed import ANY_HOUR
from cw_demo.product.tenants import (
    APPLIES,
    BUSINESS_TENANT,
    CA_FIRM_TENANT,
    NOT_APPLICABLE,
    TENANTS,
    SyntheticTenant,
)
from cw_evals.qa.world import load_world
from cw_mvp.registry import entry_named, service_settings
from domain_kernel.documents import Clause, DocumentType, ExtractionContext, ParsedDocument
from domain_kernel.ids import DocumentId
from domain_kernel.recurrence import Period, Recurrence
from notification.infrastructure.sink import MESSAGE_ID_PREFIX
from obligation.sweep import main as sweep_main
from ontology import VERSION as ONTOLOGY_VERSION
from ontology import load as load_ontology
from pipeline.application.extraction import RULE_PROMPT, RULE_PROMPT_REF, RuleExtractionStage
from pipeline.application.extractor import LlmRuleExtractor
from pipeline.infrastructure.gateway import GatewayError, GatewayProvider
from pipeline.infrastructure.prompts import load_prompt
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
    "obligation/consumer:obligation.rules",
    "notification/consumer:notification.obligations",
)
RELAYS: Final = (
    "profile/outbox-relay",
    "rulebook/outbox-relay",
    "applicability-engine/outbox-relay",
    "obligation/outbox-relay",
    "notification/outbox-relay",
    "pipeline/outbox-relay",
)
JOBS: Final = (
    "notification/notification-dispatch",
    "obligation/obligation-reminder-sweep",
    "obligation/obligation-window",
)
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
REMINDER: Final = "reminder"
REMINDER_LEADS: Final = (timedelta(days=5), timedelta(days=2), timedelta(hours=12))
"""How long before a due date the reminders step sweeps: inside the 7-, 3- and 1-day thresholds."""
CLOSURE: Final = "closure"
WITHDRAWN_NOTICE: Final = "obligation_withdrawn"
RULE_WITHDRAWN: Final = "rule_withdrawn"
PENDING_STATES: Final = frozenset({"queued", "digest_pending"})
SKIPPED: Final = "skipped (destructive; CI runs it)"
ROLLBACK_NOTE: Final = f"{NOTE}; withdrawn by the rollback check of cw-product"
TRACKED_HISTORY: Final = ("created", "started", "assigned", "closed")
"""What the tracking step's obligation went through, in order."""
TRACKING_COMMENT: Final = "Acknowledgement filed on the example portal (synthetic)"
NEEDS_REVIEW: Final = "needs_review"
CHANGES: Final = "/v1/changes"
DRY_RUNS: Final = f"{ENGINE}/dry-runs"
DRY_RUN_ACTION: Final = "applicability.dry_run"
CHANGE_PAGES: Final = 20
"""Pages of the feed the changes step reads, newest first, looking for the publication."""
WAS_PUBLISHED: Final = frozenset({"published", "superseded", "withdrawn"})
RESULTS: Final = ("applies", "not_applicable", "unsure")
PUBLIC_QUESTION: Final = "When is my GSTR-3B due?"
"""A question the structured layer answers from the registration's monthly obligations."""
GSTR3B_FORM: Final = "GSTR-3B"
QA: Final = "/v1/qa"
BULK: Final = "/v1/notification/bulk"
SEND: Final = "/v1/notification/send"
"""A service-to-service route: the public listener answers it 404."""
RECIPIENTS: Final = "/v1/notification/recipients"
CONTACT_PREFIX: Final = "public-check-"
CONTACT_DOMAIN: Final = "demo-ca-associates.invalid"
"""The step's client contact writes to ``public-check-<id>@`` this domain, reserved never to
exist; nothing reaches it, since the local product delivers through the sink."""
BULK_ACTION: Final = "notification.bulk"
OPEN: Final = ("open", "in_progress")
BULK_RULES: Final = (GSTR9, QUARTERLY)
"""The changes the step's bulk notification is about, the first one published that affects a
client: GSTR-9, and the quarterly return of the client's state once a rollback withdrew GSTR-9."""
LOOKAHEAD: Final = timedelta(days=365)
"""How far ahead the structured layer looks for the next due date of a form."""
ROUTE_NOT_FOUND: Final = "route-not-found"
SOURCES: Final = "/v1/pipeline/sources"
TASKS: Final = "/v1/pipeline/tasks"
STATUTE_SOURCES: Final = ("cgst_act", "cgst_rules", "igst_act")
UPLOAD_UNSUPPORTED: Final = "pipeline-upload-unsupported"
UPLOAD_REASON: Final = "cw-product check: an upload that is no document must be refused"
BUILT_IN_SOURCES: Final = (
    "cbic_circulars",
    "cbic_notifications",
    "cgst_act",
    "cgst_rules",
    "gstcouncil_press",
    "gstn_advisories",
    "igst_act",
    "mahagst_notifications",
)
"""The built-in sources; the statutes (cgst_act, cgst_rules, igst_act) are upload-only."""
SOURCE_STATUSES: Final = frozenset({"healthy", "fetching", "failing", "paused"})
FRESHNESS_STATES: Final = frozenset({"fresh", "late", "stale", "never"})
CRAWL_DISABLED: Final = "pipeline-crawl-disabled"
NO_SOURCE: Final = "product_check_no_such_source"
"""A key no source has: a fetch of it is refused before any lookup while crawling is off, and
is a 404 that starts nothing while it is on."""
FETCHED_SOURCE: Final = "cbic_notifications"
FETCH_ACTOR: Final = UUID("00000000-0000-4000-8000-0000000c0001")
"""The synthetic admin the check's fetches name."""
FETCH_REASON: Final = "cw-product check: a fetch must be refused while crawling is off"
TASK_NOT_FOUND: Final = "pipeline-task-not-found"
REQUEST_INVALID: Final = "request-invalid"
TRIAGE_REASON: Final = "cw-product check: a triage of a task nobody opened must be refused"
EXTRACTION_DOCUMENT: Final = ParsedDocument(
    document_id=DocumentId(UUID("00000000-0000-4000-8000-0000000c0e01")),
    doc_type=DocumentType.NOTIFICATION,
    title="Example notification of the product check",
    clauses=(
        Clause("en.p1", "Example notification of the product check"),
        Clause("en.p2", "Example text: it states no rule and is stored nowhere."),
    ),
)
"""What the extraction step asks the product's gateway about: synthetic, never stored."""
REVIEW_TASKS: Final = f"{RULEBOOK}/review/tasks"
REVIEW_STATS: Final = f"{RULEBOOK}/review/stats"
WAITING: Final = frozenset({"open", "claimed"})
"""The statuses of a review task that waits for a decision."""
IN_REVIEW_FLOW: Final = frozenset({"draft", "in_review"})
"""The statuses of a version its task can still move: a version the publish routes approved or
published while its task waited is decided with reject."""

SweepRunner = Callable[[Sequence[str]], tuple[int, dict[str, Any]]]
"""Runs ``obligation-sweep --once --json`` with more arguments: its exit code and its report."""


class StepFailedError(Exception):
    """A step's condition does not hold; the message says what is wrong."""


class NotYetError(Exception):
    """A condition does not hold yet; ``poll`` asks again until its timeout."""


class StepSkippedError(Exception):
    """The step did not run, and passes; the message says why."""


@dataclass(frozen=True, slots=True)
class CheckContext:
    product: Product
    timeout: float = TIMEOUT_SECONDS
    golden: Path = GOLDEN
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    interval: float = POLL_SECONDS
    records: ProductRecords | None = None
    """The directory and the audit log, read where no route serves them (the fanout step)."""
    destructive: bool = False
    """Whether the steps that withdraw seed rules run (the rollback step); off, they skip."""
    sweep: SweepRunner | None = None
    """``obligation-sweep`` for the reminders step; None runs it on the product's settings."""


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
    skipped: bool = False


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


def make_probe(
    context: CheckContext, headers: Mapping[str, str], purpose: str = "Recompute"
) -> Probe:
    """A new business in the business tenant, through the profile's business API, named for the
    step that makes it."""
    stamp = context.now().astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    answers = [{"key": key, "value": value} for key, value in PROBE_ANSWERS]
    for _ in range(3):
        gstin = probe_gstin(uuid4().int)
        name = f"{purpose} probe {stamp} (synthetic)"
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
                f"{tenant.name}, {registration.business.registration_name}: {len(made)} GSTR-9 "
                "obligations"
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


# ---------------------------------------------------------------- reminders


def product_sweep(product: Product) -> SweepRunner:
    """``obligation-sweep`` in this process, on the obligation settings the product's worker
    has: the product's database role, the obligation schema first on the search path, the
    rulebook at the internal listener."""
    settings = service_settings(
        entry_named("obligation"), product.settings, internal_url=product.internal_url
    )

    def run(arguments: Sequence[str]) -> tuple[int, dict[str, Any]]:
        out, err = io.StringIO(), io.StringIO()
        code = sweep_main(
            ["--once", "--json", *arguments], settings=settings, stdout=out, stderr=err
        )
        if not out.getvalue().strip():
            return code, {"error": err.getvalue().strip()}
        report: dict[str, Any] = json.loads(out.getvalue())
        return code, report

    return run


def reminders(context: CheckContext) -> list[str]:
    product = context.product
    registration = the_registration(context)
    headers = as_tenant(BUSINESS_TENANT.tenant_id)
    run = context.sweep or product_sweep(product)
    listed: list[dict[str, Any]] = ok(
        product.internal.get(
            OBLIGATIONS, params={"business_id": registration.registration_id}, headers=headers
        )
    )
    due = sorted(
        (o for o in listed if o["status"] in ("open", "in_progress") and o["due_at"]),
        key=lambda o: (str(o["due_at"]), str(o["obligation_id"])),
    )
    if not due:
        raise StepFailedError(
            f"{registration.business.name} has no open obligation with a due date: run the "
            "loop step first"
        )
    before = {str(n["id"]) for n in reminder_notices(context, registration.registration_id)}
    swept = 0
    for obligation in due:
        due_at = datetime.fromisoformat(str(obligation["due_at"]))
        for lead in REMINDER_LEADS:
            now = due_at - lead
            code, report = run(
                ["--now", now.isoformat(), "--tenant", str(BUSINESS_TENANT.tenant_id)]
            )
            swept += 1
            if code != 0:
                raise StepFailedError(f"obligation-sweep exited {code}: {report}")
            if str(obligation["obligation_id"]) not in report["reminded"]:
                continue
            notice = poll(
                partial(new_reminder, context, registration.registration_id, obligation, before),
                timeout=context.timeout,
                interval=context.interval,
            )
            return [
                f"obligation-sweep --once --now {now.isoformat()} --tenant {BUSINESS_TENANT.key}: "
                f"reminders sent {len(report['reminded'])}, obligations the window made "
                f"{len(report['created'])}",
                f"reminded: {obligation['title']}, due {obligation['due_at']}, swept "
                f"{_lead(lead)} before",
                f"reminder: {notice['channel']} {notice['state']} through the sink "
                f"({notice['provider_message_id']})",
                sink_line(product.sink_path, str(notice["provider_message_id"])),
            ]
    raise StepFailedError(
        f"{swept} sweeps reminded none of {registration.business.name}'s {len(due)} open "
        "obligations: each was reminded at every threshold already"
    )


def _lead(lead: timedelta) -> str:
    """``5 days`` or ``12 hours``."""
    if lead % timedelta(days=1):
        return f"{lead // timedelta(hours=1)} hours"
    return f"{lead.days} days"


def reminder_notices(context: CheckContext, business_id: str) -> list[dict[str, Any]]:
    page = ok(
        context.product.internal.get(
            NOTIFICATIONS,
            params={"business_id": business_id, "limit": 200},
            headers=as_tenant(BUSINESS_TENANT.tenant_id),
        )
    )
    return [n for n in page["items"] if n["occasion"] == REMINDER]


def new_reminder(
    context: CheckContext, business_id: str, obligation: Mapping[str, Any], before: set[str]
) -> dict[str, Any]:
    """A reminder about ``obligation`` that was not there before the sweep, sent through the
    sink."""
    fresh = [
        n
        for n in reminder_notices(context, business_id)
        if str(n["obligation_id"]) == str(obligation["obligation_id"])
        and str(n["id"]) not in before
    ]
    sent = [
        n
        for n in fresh
        if n["state"] in SENT_STATES and str(n["provider_message_id"]).startswith(MESSAGE_ID_PREFIX)
    ]
    if not sent:
        states = ", ".join(f"{n['channel']} {n['state']}" for n in fresh) or "none queued"
        raise NotYetError(f"no reminder sent through the sink yet ({states})")
    return sent[0]


# ---------------------------------------------------------------- rollback


def rollback(context: CheckContext) -> list[str]:
    if not context.destructive:
        raise StepSkippedError(SKIPPED)
    product = context.product
    versions = rule_versions(product, GSTR9)
    if not versions:
        raise StepFailedError(f"{GSTR9} has no version: run make seed SERVICE=rulebook")
    latest = versions[-1]
    version_id, status = str(latest["rule_version_id"]), str(latest["status"])
    if status not in ("published", "withdrawn"):
        raise StepFailedError(f"{GSTR9} is {status}: the fanout step publishes it first")
    holders = gstr9_holders(context, version_id)
    missing = [tenant.name for tenant in TENANTS if tenant.key not in holders]
    if missing:
        raise StepFailedError(
            f"{GSTR9} has no obligation in {', '.join(missing)}: run the fanout step first"
        )
    if status == "published":
        body = {"actor_id": str(FIRST_REVIEWER.user_id), "note": ROLLBACK_NOTE}
        ok(
            product.internal.post(
                f"{RULEBOOK}/rule-versions/{version_id}/withdraw",
                json=body,
                headers=product.review_headers(),
            )
        )
        lines = [f"{GSTR9} v{latest['version']} withdrawn ({version_id}) as {FIRST_REVIEWER.name}"]
    else:
        lines = [f"{GSTR9} was withdrawn before ({version_id}): checking what followed"]
    for key, found in holders.items():
        tenant = found[0][0]
        closed = poll(
            partial(withdrawn_obligations, context, tenant, [r for _, r in found], version_id),
            timeout=context.timeout,
            interval=context.interval,
        )
        notices = poll(
            partial(withdrawal_notices, context, tenant, [r for _, r in found], closed),
            timeout=context.timeout,
            interval=context.interval,
        )
        states = sorted({f"{n['channel']} {n['state']}" for n in notices})
        lines.append(
            f"{tenant.name}: {len(closed)} GSTR-9 obligations closed ({RULE_WITHDRAWN}); "
            f"withdrawal notices {', '.join(states)}"
        )
        if key == BUSINESS_TENANT.key:
            sent = next(n for n in notices if n["state"] in SENT_STATES)
            lines.append(sink_line(product.sink_path, str(sent["provider_message_id"])))
    return lines


def gstr9_holders(
    context: CheckContext, version_id: str
) -> dict[str, list[tuple[SyntheticTenant, SeededRegistration]]]:
    """The synthetic registrations GSTR-9 applies to that hold obligations of the version, by
    tenant."""
    found: dict[str, list[tuple[SyntheticTenant, SeededRegistration]]] = {}
    for tenant in TENANTS:
        for registration in registrations(context.product, tenant):
            if registration.business.expected.get(GSTR9) != APPLIES:
                continue
            listed = ok(
                context.product.internal.get(
                    OBLIGATIONS,
                    params={
                        "business_id": registration.registration_id,
                        "rule_version_id": version_id,
                    },
                    headers=as_tenant(tenant.tenant_id),
                )
            )
            if listed:
                found.setdefault(tenant.key, []).append((tenant, registration))
    return found


def withdrawn_obligations(
    context: CheckContext,
    tenant: SyntheticTenant,
    held: Sequence[SeededRegistration],
    version_id: str,
) -> list[dict[str, Any]]:
    """Every obligation of the version of ``held``, once each is closed as withdrawn."""
    closed: list[dict[str, Any]] = []
    for registration in held:
        listed: list[dict[str, Any]] = answered(
            context.product.internal.get(
                OBLIGATIONS,
                params={"business_id": registration.registration_id, "rule_version_id": version_id},
                headers=as_tenant(tenant.tenant_id),
            )
        )
        still = [o for o in listed if (o["status"], o["closed_reason"]) != (CLOSED, RULE_WITHDRAWN)]
        if still:
            raise NotYetError(
                f"{len(still)} GSTR-9 obligations of {registration.business.name} are not closed "
                f"as {RULE_WITHDRAWN} yet"
            )
        closed += listed
    return closed


def withdrawal_notices(
    context: CheckContext,
    tenant: SyntheticTenant,
    held: Sequence[SeededRegistration],
    closed: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """The withdrawal notices about the closed obligations: one sent through the sink, or for a
    tenant that hears by digest, queued for it."""
    wanted = {str(o["obligation_id"]) for o in closed}
    notices: list[dict[str, Any]] = []
    for registration in held:
        page = answered(
            context.product.internal.get(
                NOTIFICATIONS,
                params={"business_id": registration.registration_id, "limit": 200},
                headers=as_tenant(tenant.tenant_id),
            )
        )
        notices += [
            n
            for n in page["items"]
            if n["occasion"] == CLOSURE
            and n["template_key"] == WITHDRAWN_NOTICE
            and str(n["obligation_id"]) in wanted
        ]
    sent = [
        n
        for n in notices
        if n["state"] in SENT_STATES and str(n["provider_message_id"]).startswith(MESSAGE_ID_PREFIX)
    ]
    if tenant.kind == "business" and not sent:
        states = ", ".join(f"{n['channel']} {n['state']}" for n in notices) or "none queued"
        raise NotYetError(f"no withdrawal notice sent through the sink yet ({states})")
    if not sent and not [n for n in notices if n["state"] in PENDING_STATES]:
        raise NotYetError(f"no withdrawal notice queued for {tenant.name} yet")
    return notices


# ---------------------------------------------------------------- tracking


def keyed(headers: Mapping[str, str], key: str | None = None) -> dict[str, str]:
    """``headers`` with an Idempotency-Key: ``key``, or a new one."""
    return {**headers, IDEMPOTENCY_HEADER: key or str(uuid4())}


def tracking(context: CheckContext) -> list[str]:
    product = context.product
    headers = as_tenant(BUSINESS_TENANT.tenant_id)
    versions = {
        str(version["rule_key"]): version
        for version in published_in_force(product, today_in_india(context.now()))
    }
    if MONTHLY not in versions:
        raise StepFailedError(f"{MONTHLY} is not published: run cw-product seed")
    monthly = str(versions[MONTHLY]["rule_version_id"])
    probe = make_probe(context, headers, "Tracking")

    def first_due() -> dict[str, Any]:
        listed: list[dict[str, Any]] = answered(
            product.internal.get(
                OBLIGATIONS,
                params={"business_id": probe.registration_id, "rule_version_id": monthly},
                headers=headers,
            )
        )
        due = sorted(
            (o for o in listed if o["status"] == "open"),
            key=lambda o: (str(o["due_at"]), str(o["obligation_id"])),
        )
        if not due:
            raise NotYetError(f"no open obligation of {MONTHLY} yet for {probe.name}")
        return due[0]

    target = poll(first_due, timeout=context.timeout, interval=context.interval)
    decided, period, due_on = due_next(context, probe, versions[MONTHLY])
    if (target["period_label"], _ist_day(str(target["due_at"]))) != (period.label, due_on):
        raise StepFailedError(
            f"the first {MONTHLY} obligation of {probe.name}, decided on {decided}, is "
            f"{target['period_label']} due {target['due_at']}, not {period.label} due {due_on}, "
            "the return it has to file next"
        )
    route = f"{OBLIGATIONS}/{target['obligation_id']}"
    owner = str(BUSINESS_TENANT.owner_id)
    started = ok(
        product.internal.post(f"{route}/status", json={"action": "start"}, headers=keyed(headers))
    )
    assigned = ok(
        product.internal.put(
            f"{route}/assignee", json={"assignee_id": owner}, headers=keyed(headers)
        )
    )
    if (started["status"], assigned["assignee_id"]) != ("in_progress", owner):
        raise StepFailedError(
            f"the obligation is {started['status']} and assigned to {assigned['assignee_id']}"
        )
    completed, replayed = complete_twice(product, route, keyed(headers))
    comment = ok(
        product.internal.post(
            f"{route}/comments", json={"body": TRACKING_COMMENT}, headers=keyed(headers)
        ),
        201,
    )
    detail: dict[str, Any] = ok(product.internal.get(route, headers=headers))
    review = tracked_detail(detail, comment)
    return [
        f"probe: {probe.name}, registration {probe.registration_id}; {MONTHLY} "
        f"{target['period_label']} due {target['due_at']}, the return due next on {decided}, "
        "the day it was decided",
        f"started, assigned to {BUSINESS_TENANT.owner_name} and completed "
        f"({completed['status']}); the same complete again with its Idempotency-Key was "
        f"replayed ({REPLAYED_HEADER}: {replayed}) with the same answer",
        f"history: {', '.join(c['kind'] for c in detail['history'])}; one closure",
        f"reviewed by {review} on {detail['rule_version']['published_at']}, seed status "
        f"{detail['rule_version']['seed_status']}; {len(detail['citations'])} verified citations",
        f"comment by {comment['author_label']}: {comment['body']}",
    ]


def due_next(
    context: CheckContext, probe: Probe, version: Mapping[str, Any]
) -> tuple[date, Period, date]:
    """The day in India the probe was first decided to file ``version``'s return, the period
    whose return it files next from that day, and its due date: the first period still due that
    day which the version governs (it is in force on the period's last day), where the obligation
    service's window starts (``Recurrence.periods_due``). On 6 October that is September, due 20
    October; on 25 October, October, due 20 November."""
    page = ok(
        context.product.internal.get(
            f"{ENGINE}/businesses/{probe.registration_id}/decisions",
            params={"rule_version_id": str(version["rule_version_id"]), "limit": 200},
            headers=as_tenant(BUSINESS_TENANT.tenant_id),
        )
    )
    days = [
        today_in_india(datetime.fromisoformat(str(item["decided_at"])))
        for item in page["items"]
        if item["result"] == APPLIES
    ]
    if not days or version["recurrence"] is None:
        raise StepFailedError(
            f"{probe.name} has obligations of {version['rule_key']} but no decision that it "
            "applies, or the version does not recur"
        )
    decided = min(days)
    recurrence = Recurrence.from_mapping(version["recurrence"])
    effective_from = date.fromisoformat(str(version["effective_from"]))
    governed = [p for p in recurrence.periods_due(decided, 1) if p.end > effective_from]
    if not governed:
        raise StepFailedError(
            f"{version['rule_key']} is in force from {effective_from}, after {probe.name} was "
            f"decided on {decided}"
        )
    return decided, governed[0], recurrence.due_date(governed[0])


def complete_twice(
    product: Product, route: str, headers: Mapping[str, str]
) -> tuple[dict[str, Any], str]:
    """The same complete sent twice with one Idempotency-Key: the first answer, and the replay
    header of the second, whose answer must be the first's."""
    first = product.internal.post(f"{route}/status", json={"action": "complete"}, headers=headers)
    second = product.internal.post(f"{route}/status", json={"action": "complete"}, headers=headers)
    completed: dict[str, Any] = ok(first)
    if ok(second) != completed:
        raise StepFailedError("the second complete with the same key answered otherwise")
    replayed = second.headers.get(REPLAYED_HEADER, "")
    if completed["status"] != "done" or replayed != "true":
        raise StepFailedError(
            f"the obligation is {completed['status']}, and the second complete was "
            f"{'replayed' if replayed == 'true' else 'not replayed'}"
        )
    return completed, replayed


def tracked_detail(detail: Mapping[str, Any], comment: Mapping[str, Any]) -> str:
    """Check the detail of the tracked obligation; the names of the approvers it shows."""
    kinds = tuple(str(change["kind"]) for change in detail["history"])
    if kinds != TRACKED_HISTORY:
        raise StepFailedError(f"the history reads {', '.join(kinds)}")
    review = detail["rule_version"]
    if review is None:
        raise StepFailedError("the detail has no facts of its rule version")
    names = {str(analyst.user_id): analyst.name for analyst in REVIEWERS}
    if set(review["approved_by"]) != set(names):
        raise StepFailedError(
            f"the reviewed-by data names {review['approved_by']}, not both synthetic reviewers"
        )
    if review["seed_status"] != NEEDS_REVIEW or review["reviewed"]:
        raise StepFailedError(
            f"the seed rule reads {review['seed_status']}: a synthetic approval reviews nothing"
        )
    if not detail["citations"]:
        raise StepFailedError("the detail shows no verified citation")
    if [c["comment_id"] for c in detail["comments"]] != [comment["comment_id"]]:
        raise StepFailedError("the detail does not list the comment")
    return " and ".join(names[approver] for approver in sorted(review["approved_by"]))


# ---------------------------------------------------------------- changes


def changes(context: CheckContext) -> list[str]:
    records = context.records
    if records is None:
        raise StepFailedError(
            "the changes step reads audit.event and the engine's rows of a tenant: set "
            "CW_PRODUCT_RECORDS_URL (make product-check passes it)"
        )
    product = context.product
    published = [v for v in rule_versions(product, GSTR9) if v["status"] in WAS_PUBLISHED]
    if not published:
        raise StepFailedError(f"{GSTR9} was never published: run the fanout step first")
    version = published[-1]
    version_id = str(version["rule_version_id"])
    item = publication_in_feed(product, version_id)
    reviewers = feed_reviewers(item)
    impact = poll(
        partial(affected_clients, context, version_id),
        timeout=context.timeout,
        interval=context.interval,
    )
    lines = [
        f"GET {CHANGES}: {GSTR9} v{version['version']} published {item['changed_at']}, approved "
        f"by {reviewers}, seed status {item['seed_status']}, {len(item['citations'])} verified "
        f"citations (now {item['status']})",
        f"{CA_FIRM_TENANT.name}: {GSTR9} applies to "
        + ", ".join(
            f"{business['business_id']} of client {client['entity_id']}"
            for client in impact["items"]
            for business in client["businesses"]
        )
        + f"; the fan-out {impact['fan_out']['status']}",
    ]
    return lines + dry_run_matches(context, records, version_id)


def publication_in_feed(product: Product, version_id: str) -> dict[str, Any]:
    """The feed's item of the version's publication, read from its ``published_at`` on."""
    detail = ok(product.internal.get(f"{RULEBOOK}/rule-versions/{version_id}"))
    params: dict[str, str | int] = {"since": str(detail["published_at"]), "limit": 100}
    for _ in range(CHANGE_PAGES):
        page = ok(product.internal.get(CHANGES, params=params))
        for item in page["items"]:
            if (item["kind"], item["rule_version_id"]) == ("published", version_id):
                found: dict[str, Any] = item
                return found
        if page["next_cursor"] is None:
            break
        params["cursor"] = str(page["next_cursor"])
    raise StepFailedError(f"GET {CHANGES} does not list the publication of {GSTR9} {version_id}")


def feed_reviewers(item: Mapping[str, Any]) -> str:
    """Check the publication's item: both synthetic reviewers approved it, its seed status is
    still needs_review and it cites verified clauses; the reviewers' names."""
    names = {str(analyst.user_id): analyst.name for analyst in REVIEWERS}
    if set(item["approved_by"]) != set(names):
        raise StepFailedError(
            f"the feed names {item['approved_by']} as approvers, not both synthetic reviewers"
        )
    if item["seed_status"] != NEEDS_REVIEW:
        raise StepFailedError(
            f"the feed reads {GSTR9} {item['seed_status']}: a synthetic approval reviews nothing"
        )
    if item["rule_key"] != GSTR9 or not item["citations"]:
        raise StepFailedError(f"the feed's item of {GSTR9} cites no verified clause")
    return " and ".join(names[approver] for approver in sorted(item["approved_by"]))


def affected_clients(context: CheckContext, version_id: str) -> dict[str, Any]:
    """The impact of the version on the CA firm, ``result=applies``, once it lists exactly the
    firm's registrations the answers call for, each under its own client."""
    product = context.product
    expected = {
        seeded.registration_id: seeded.entity_id
        for seeded in registrations(product, CA_FIRM_TENANT)
        if seeded.business.expected.get(GSTR9) == APPLIES
    }
    if not expected:
        raise StepFailedError(f"{GSTR9} applies to no registration of {CA_FIRM_TENANT.name}")
    impact: dict[str, Any] = answered(
        product.internal.get(
            f"{CHANGES}/{version_id}/impact",
            params={"result": APPLIES, "limit": 200},
            headers=as_tenant(CA_FIRM_TENANT.tenant_id),
        )
    )
    listed = {
        str(business["business_id"]): str(client["entity_id"])
        for client in impact["items"]
        for business in client["businesses"]
    }
    if listed != expected:
        raise NotYetError(
            f"the impact on {CA_FIRM_TENANT.name} lists {sorted(listed.items())}; the answers "
            f"call for {sorted(expected.items())}"
        )
    if impact["fan_out"] is None or impact["fan_out"]["status"] != "completed":
        raise NotYetError(f"the impact names the fan-out {impact['fan_out']}, not completed")
    return impact


def dry_run_matches(context: CheckContext, records: ProductRecords, version_id: str) -> list[str]:
    """A dry run of the version scoped to the CA firm counts what the firm's latest decisions
    of it count, and writes its audit row and nothing else."""
    product = context.product
    firm = CA_FIRM_TENANT
    headers = as_tenant(firm.tenant_id)
    whole: dict[str, Any] = ok(
        product.internal.get(
            f"{CHANGES}/{version_id}/impact", params={"limit": 200}, headers=headers
        )
    )
    decided = {
        str(business["business_id"]): str(business["result"])
        for client in whole["items"]
        for business in client["businesses"]
    }
    listed = records.listed(decided)
    expected = {
        result: sum(1 for business in listed if decided[business] == result) for result in RESULTS
    }
    before = records.engine_rows(firm.tenant_id)
    since = context.now() - timedelta(minutes=1)
    request_id = uuid4().hex
    report: dict[str, Any] = ok(
        product.internal.post(
            DRY_RUNS,
            json={
                "rule_version_id": version_id,
                "scope": {"tenant_id": str(firm.tenant_id), "sample_size": 50},
            },
            headers={"x-request-id": request_id},
        )
    )
    after = records.engine_rows(firm.tenant_id)
    if report["counts"] != expected:
        raise StepFailedError(
            f"the dry run counts {report['counts']}; the firm's decisions of {GSTR9} for the "
            f"{len(listed)} registrations the directory lists count {expected}"
        )
    if (report["businesses_total"], report["evaluated"], report["skipped"]) != (
        len(listed),
        len(listed),
        0,
    ):
        raise StepFailedError(
            f"the dry run read {report['businesses_total']} directory entries and decided "
            f"{report['evaluated']} ({report['skipped']} skipped); the directory lists "
            f"{len(listed)} of the firm's registrations with a decision of {GSTR9}"
        )
    differ = [
        sample["business_id"]
        for sample in report["samples"]
        if decided.get(str(sample["business_id"])) != sample["result"]
    ]
    if differ:
        raise StepFailedError(f"the dry run decided {differ} otherwise than the fan-out")
    if after != before:
        raise StepFailedError(f"the dry run wrote to the engine: {before} became {after}")
    rows = [
        row
        for row in records.audit_entries(actions=(DRY_RUN_ACTION,), since=since)
        if row.correlation_id == request_id
    ]
    if len(rows) != 1 or rows[0].tenant_id is not None or rows[0].subject_id != version_id:
        raise StepFailedError(
            f"audit.event holds {len(rows)} {DRY_RUN_ACTION} rows of the request, not one of "
            "no tenant about the version"
        )
    counts = ", ".join(f"{count} {result}" for result, count in report["counts"].items())
    return [
        f"dry run of {GSTR9} ({report['status']}) for {firm.name}: {report['evaluated']} of "
        f"{report['businesses_total']} decided ({counts}), as the firm's decisions of the "
        "registrations the directory lists count",
        f"wrote one {DRY_RUN_ACTION} row of no tenant by {rows[0].actor_label}; the firm's "
        + ", ".join(f"{table} {count}" for table, count in after.items())
        + " rows unchanged",
    ]


# ---------------------------------------------------------------- public


def public(context: CheckContext) -> list[str]:
    records = context.records
    if records is None:
        raise StepFailedError(
            "the public step reads the bulk notification's audit rows: set "
            "CW_PRODUCT_RECORDS_URL (make product-check passes it)"
        )
    registration = the_registration(context)
    lines = public_obligations(context, registration)
    lines += public_answer(context, registration)
    lines += public_bulk(context, records)
    lines += internal_hidden(context)
    return lines


def public_obligations(context: CheckContext, registration: SeededRegistration) -> list[str]:
    """The registration's obligations through the public listener: what the step saw."""
    product = context.product
    headers = as_tenant(BUSINESS_TENANT.tenant_id)
    path = f"{BUSINESSES}/{registration.registration_id}/obligations"
    whole: dict[str, Any] = ok(product.public.get(path, params={"limit": 200}, headers=headers))
    items: list[dict[str, Any]] = whole["items"]
    if not items:
        raise StepFailedError(f"GET {path} lists nothing: run the loop step first")
    paged: list[dict[str, Any]] = []
    params: dict[str, str | int] = {"limit": 1}
    for _ in range(len(items)):
        page = ok(product.public.get(path, params=params, headers=headers))
        paged += page["items"]
        if page["next_cursor"] is None:
            break
        params = {"limit": 1, "cursor": str(page["next_cursor"])}
    if [item["obligation_id"] for item in paged] != [item["obligation_id"] for item in items]:
        raise StepFailedError(f"pages of one of GET {path} differ from one page of 200")
    if any(item["business_id"] != registration.registration_id for item in items):
        raise StepFailedError(f"GET {path} lists another business's obligations")
    dated = [str(item["due_at"]) for item in items if item["due_at"]]
    if dated != sorted(dated, key=datetime.fromisoformat):
        raise StepFailedError(f"GET {path} is not by due date")
    titled = [item for item in items if item["rule_version"] and item["rule_version"]["title"]]
    if not titled:
        raise StepFailedError(f"no obligation of GET {path} carries its rule's title")
    still_open = ok(
        product.public.get(path, params={"status": list(OPEN), "limit": 200}, headers=headers)
    )["items"]
    if any(item["status"] not in OPEN for item in still_open):
        raise StepFailedError(f"GET {path}?status=open&status=in_progress lists closed ones")
    today = today_in_india(context.now())
    too_long = product.public.get(
        path,
        params={"due_from": today.isoformat(), "due_to": (today + timedelta(days=366)).isoformat()},
        headers=headers,
    )
    if (too_long.status_code, problem_slug(too_long)) != (422, "obligation-window-invalid"):
        raise StepFailedError(f"a window of 367 days answered {too_long.status_code}, not 422")
    theirs = product.public.get(path, headers=as_tenant(CA_FIRM_TENANT.tenant_id))
    if (theirs.status_code, problem_slug(theirs)) != (404, "obligation-business-not-found"):
        raise StepFailedError(
            f"{CA_FIRM_TENANT.name} reading {path} answered {theirs.status_code}, not 404"
        )
    rule = titled[0]["rule_version"]
    return [
        f"GET {path} on the public listener: {len(items)} obligations by due date, pages of one "
        f"alike; {len(titled)} with their rule's title ({rule['title']}, seed status "
        f"{rule['seed_status']}); {len(still_open)} open or in progress",
        f"a window of 367 days: 422 obligation-window-invalid; {CA_FIRM_TENANT.name}: 404 "
        "obligation-business-not-found",
    ]


def public_answer(context: CheckContext, registration: SeededRegistration) -> list[str]:
    """``POST /v1/qa`` through the public listener answers when the registration's GSTR-3B is due
    next, from the structured layer, as the product (the knowledge graph off) should.

    The expected sentence names the earliest open obligation due from today (within a year) of
    a version in force whose title, or its rule's, names the form, as the public listing has it
    just before the question: the return due next on whatever day the check runs, which is the
    previous period's while its due date is still ahead (September's, due 20 October, on 6
    October). When a decision made meanwhile changes the listing, both are read again."""
    product = context.product
    headers = as_tenant(BUSINESS_TENANT.tenant_id)
    today = today_in_india(context.now())
    in_force = {str(version["rule_version_id"]) for version in published_in_force(product, today)}
    path = f"{BUSINESSES}/{registration.registration_id}/obligations"
    window: dict[str, str | int | list[str]] = {
        "status": list(OPEN),
        "due_from": today.isoformat(),
        "due_to": (today + LOOKAHEAD).isoformat(),
        "limit": 200,
    }
    body = {
        "question": PUBLIC_QUESTION,
        "as_of": today.isoformat(),
        "business_node_id": registration.registration_id,
    }

    def earliest() -> tuple[date, str]:
        page = ok(product.public.get(path, params=window, headers=headers))
        due = sorted(
            (_ist_day(str(item["due_at"])), str(item["title"]))
            for item in page["items"]
            if item["rule_version_id"] in in_force
            and item["due_at"]
            and (
                names_form(str(item["title"]), GSTR3B_FORM)
                or names_form(str((item["rule_version"] or {}).get("title", "")), GSTR3B_FORM)
            )
        )
        if not due:
            raise StepFailedError(
                f"{registration.business.name} has no open {GSTR3B_FORM} obligation due within a "
                "year: run the loop step first"
            )
        return due[0]

    def answered_alike() -> dict[str, Any]:
        day, title = earliest()
        answer: dict[str, Any] = ok(product.public.post(QA, json=body, headers=headers))
        if (answer["outcome"], answer["layer"]) != ("answered", "structured"):
            raise StepFailedError(
                f"POST {QA} answered {answer['outcome']} from the {answer['layer']} layer "
                f"({answer['reason']}); with the knowledge graph off the structured layer answers "
                "it from the obligations"
            )
        expected = f"Your next {GSTR3B_FORM} is due on {day.day} {day:%B %Y}: {title}."
        if answer["answer"] != expected:
            raise NotYetError(
                f"POST {QA} answered {answer['answer']!r}, not {expected!r}, the earliest open "
                f"{GSTR3B_FORM} obligation the listing has due from {today}"
            )
        if not answer["citations"]:
            raise StepFailedError(f"POST {QA} answered {expected!r} without a citation")
        return answer

    answer = poll(answered_alike, timeout=context.timeout, interval=context.interval)
    foreign = product.public.post(QA, json=body, headers=as_tenant(CA_FIRM_TENANT.tenant_id))
    if (foreign.status_code, problem_slug(foreign)) != (404, "qa-business-not-found"):
        raise StepFailedError(
            f"{CA_FIRM_TENANT.name} asking about the registration answered "
            f"{foreign.status_code}, not 404"
        )
    cited = answer["citations"][0]
    return [
        f"POST {QA} {PUBLIC_QUESTION!r}: {answer['answer']} (structured layer, "
        f"{len(answer['citations'])} verified citations, first {cited['clause_ref']})",
        f"{CA_FIRM_TENANT.name} asking about the registration: 404 qa-business-not-found",
    ]


def _ist_day(instant: str) -> date:
    return datetime.fromisoformat(instant).astimezone(IST).date()


def names_form(title: str, form: str) -> bool:
    """Whether ``title`` names the form as a whole code (GSTR-3B, not GSTR-3), as the structured
    layer reads a title."""
    folded = title.casefold().replace(" - ", "-")
    code = re.escape(form.casefold())
    return re.search(rf"(?<![a-z0-9-]){code}(?![a-z0-9-])", folded) is not None


def public_bulk(context: CheckContext, records: ProductRecords) -> list[str]:
    """The CA firm's bulk change card to the clients a change affects, through the public
    listener, to a client contact made for the step and removed after it."""
    product = context.product
    firm = CA_FIRM_TENANT
    headers = as_tenant(firm.tenant_id)
    rule_key, version_id, affected = bulk_change(context)
    lines = lift_contacts(product, affected)
    contact, address = register_contact(product, affected)
    try:
        since = context.now() - timedelta(minutes=1)
        body = {"rule_version_id": version_id, "business_ids": affected, "kind": "change_card"}
        key, first_request, second_request = str(uuid4()), uuid4().hex, uuid4().hex
        first = product.public.post(
            BULK,
            json=body,
            headers={**headers, IDEMPOTENCY_HEADER: key, "x-request-id": first_request},
        )
        sent: dict[str, Any] = ok(first, 201)
        told = len(affected)
        counts = (
            sent["queued"],
            sent["notifications_queued"],
            sent["skipped_duplicate"],
            sent["skipped_no_recipient"],
            sent["skipped_not_affected"],
        )
        if counts != (told, told, 0, 0, 0):
            raise StepFailedError(
                f"POST {BULK} of {rule_key} answered queued, cards, duplicate, no recipient, not "
                f"affected {counts}; the contact follows {told} affected clients"
            )
        replay = product.public.post(BULK, json=body, headers={**headers, IDEMPOTENCY_HEADER: key})
        if ok(replay, 201) != sent or replay.headers.get(REPLAYED_HEADER) != "true":
            raise StepFailedError(
                f"the same POST {BULK} with its Idempotency-Key answered otherwise"
            )
        again: dict[str, Any] = ok(
            product.public.post(
                BULK,
                json=body,
                headers={
                    **headers,
                    IDEMPOTENCY_HEADER: str(uuid4()),
                    "x-request-id": second_request,
                },
            ),
            201,
        )
        if (again["queued"], again["skipped_duplicate"], again["notifications_queued"]) != (
            0,
            told,
            0,
        ):
            raise StepFailedError(
                f"a new key for the same change and clients queued {again['notifications_queued']} "
                f"cards and found {again['skipped_duplicate']} duplicates, not 0 and {told}"
            )
        audited = audited_bulk(records, since, firm.tenant_id, (first_request, second_request))
        card = poll(
            partial(contact_card, context, contact, affected),
            timeout=context.timeout,
            interval=context.interval,
        )
    finally:
        ok(product.internal.delete(f"{RECIPIENTS}/{contact}", headers=headers), 204)
    return [
        *lines,
        f"POST {BULK} of {rule_key} ({version_id}) on the public listener as {firm.name}: "
        f"{told} clients told, {sent['notifications_queued']} card to the client contact, none "
        "to the firm's admin; the same key replayed (Idempotent-Replayed: true) with the same "
        f"answer; a new key found {again['skipped_duplicate']} duplicate",
        audited,
        f"the contact's card: {card['channel']} {card['state']} through the sink "
        f"({card['provider_message_id']}); the contact ({address}) removed",
        sink_line(product.sink_path, str(card["provider_message_id"])),
    ]


def bulk_change(context: CheckContext) -> tuple[str, str, list[str]]:
    """The first change of ``BULK_RULES`` published that affects one of the firm's clients:
    its rule key, its version and the registrations its impact lists."""
    product = context.product
    for rule_key in BULK_RULES:
        published = [v for v in rule_versions(product, rule_key) if v["status"] == "published"]
        if not published:
            continue
        version_id = str(published[-1]["rule_version_id"])
        impact = ok(
            product.public.get(
                f"{CHANGES}/{version_id}/impact",
                params={"result": APPLIES, "limit": 200},
                headers=as_tenant(CA_FIRM_TENANT.tenant_id),
            )
        )
        affected = [str(b["business_id"]) for c in impact["items"] for b in c["businesses"]]
        if affected:
            return rule_key, version_id, affected
    raise StepFailedError(
        f"neither {' nor '.join(BULK_RULES)} is published with a client of "
        f"{CA_FIRM_TENANT.name} it applies to: run make product-seed and the fanout step"
    )


def _is_contact(recipient: Mapping[str, Any]) -> bool:
    return any(
        str(entry["address"]).startswith(CONTACT_PREFIX)
        and str(entry["address"]).endswith(f"@{CONTACT_DOMAIN}")
        for entry in recipient["addresses"]
    )


def lift_contacts(product: Product, affected: Sequence[str]) -> list[str]:
    """Remove the client contacts an interrupted check left."""
    headers = as_tenant(CA_FIRM_TENANT.tenant_id)
    left: set[str] = set()
    for business in affected:
        page = ok(
            product.internal.get(
                RECIPIENTS, params={"business_id": business, "limit": 200}, headers=headers
            )
        )
        left |= {str(item["id"]) for item in page["items"] if _is_contact(item)}
    for recipient in sorted(left):
        ok(product.internal.delete(f"{RECIPIENTS}/{recipient}", headers=headers), 204)
    return [f"removed {len(left)} client contacts an interrupted check left"] if left else []


def register_contact(product: Product, affected: Sequence[str]) -> tuple[str, str]:
    """A client's owner who follows the affected clients, on a mailbox that cannot exist, opted in
    with no quiet hours: the person a bulk change card is for."""
    firm = CA_FIRM_TENANT
    names = {
        seeded.registration_id: seeded.business.name for seeded in registrations(product, firm)
    }
    recipient = str(uuid4())
    address = f"{CONTACT_PREFIX}{recipient[:8]}@{CONTACT_DOMAIN}"
    body = {
        "role": "owner",
        "language": "en",
        "digest_mode": "off",
        "addresses": [{"channel": "email", "address": address}],
        "businesses": [
            {"business_id": business, "label": names.get(business, "")} for business in affected
        ],
    }
    ok(
        product.internal.put(
            f"{RECIPIENTS}/{recipient}", json=body, headers=as_tenant(firm.tenant_id)
        )
    )
    ok(
        product.internal.put(
            f"/v1/notification/preferences/email/{address}",
            json={
                "opted_in": True,
                "source": "api",
                "language": "en",
                "quiet_hours_start": ANY_HOUR,
                "quiet_hours_end": ANY_HOUR,
            },
        )
    )
    return recipient, address


def audited_bulk(
    records: ProductRecords, since: datetime, tenant: UUID, requests: Sequence[str]
) -> str:
    """One ``notification.bulk`` row of the firm per request that ran, found by its correlation
    id; the replay ran nothing."""
    rows = [
        row
        for row in records.audit_entries(actions=(BULK_ACTION,), since=since)
        if row.correlation_id in requests
    ]
    if sorted(str(row.correlation_id) for row in rows) != sorted(requests):
        raise StepFailedError(
            f"audit.event holds {len(rows)} {BULK_ACTION} rows of the step's {len(requests)} "
            "requests that ran"
        )
    if any(row.tenant_id != tenant for row in rows):
        raise StepFailedError(f"a {BULK_ACTION} row is not the firm's")
    return f"audit.event: {len(rows)} {BULK_ACTION} rows of the firm, by {rows[0].actor_label}"


def contact_card(context: CheckContext, contact: str, affected: Sequence[str]) -> dict[str, Any]:
    """The contact's change card, once it went out through the sink: one per client."""
    product = context.product
    cards: list[dict[str, Any]] = []
    for business in affected:
        page = answered(
            product.internal.get(
                NOTIFICATIONS,
                params={"business_id": business, "limit": 200},
                headers=as_tenant(CA_FIRM_TENANT.tenant_id),
            )
        )
        cards += [
            n
            for n in page["items"]
            if n["occasion"] == CHANGE_CARD and n["recipient_id"] == contact
        ]
    if len(cards) > len(affected):
        raise StepFailedError(
            f"the contact has {len(cards)} change cards for {len(affected)} clients"
        )
    sent = [
        card
        for card in cards
        if card["state"] in SENT_STATES
        and str(card["provider_message_id"]).startswith(MESSAGE_ID_PREFIX)
    ]
    if len(sent) < len(affected):
        states = ", ".join(f"{c['channel']} {c['state']}" for c in cards) or "none queued"
        raise NotYetError(f"the contact's change card has not gone through the sink yet ({states})")
    return sent[0]


def internal_hidden(context: CheckContext) -> list[str]:
    """A service-to-service route stays off the public listener."""
    response = context.product.public.post(
        SEND, json={}, headers=as_tenant(CA_FIRM_TENANT.tenant_id)
    )
    if (response.status_code, problem_slug(response)) != (404, ROUTE_NOT_FOUND):
        raise StepFailedError(
            f"POST {SEND} on the public listener answered {response.status_code}, not 404"
        )
    return [f"POST {SEND} on the public listener: 404 {ROUTE_NOT_FOUND}"]


# ---------------------------------------------------------------- sources


def _source_problems(item: Mapping[str, Any]) -> list[str]:
    key = item.get("key", "?")
    found: list[str] = []
    if item.get("status") not in SOURCE_STATUSES:
        found.append(f"{key} has the status {item.get('status')!r}")
    if item.get("freshness", {}).get("state") not in FRESHNESS_STATES:
        found.append(f"{key} has no freshness")
    if not item.get("regulator") or not item.get("name"):
        found.append(f"{key} has no regulator or name")
    if not isinstance(item.get("cadence_seconds"), int) or item["cadence_seconds"] < 60:
        found.append(f"{key} has no cadence")
    return found


def _latest_runs(product: Product) -> dict[str, str | None]:
    items = ok(product.internal.get(SOURCES))["items"]
    return {
        item["key"]: None if item["latest_run"] is None else item["latest_run"]["run_id"]
        for item in items
    }


def _fetch(product: Product, key: str) -> httpx2.Response:
    return product.internal.post(
        f"{SOURCES}/{key}/fetch",
        json={"actor_id": str(FETCH_ACTOR), "reason": FETCH_REASON},
        headers=product.write_headers(),
    )


def sources(context: CheckContext) -> list[str]:
    product = context.product

    def listed() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = answered(product.internal.get(SOURCES))["items"]
        missing = sorted(set(BUILT_IN_SOURCES) - {item["key"] for item in items})
        if missing:
            raise NotYetError(f"{SOURCES} lacks {', '.join(missing)}: has the worker started?")
        return items

    items = poll(listed, timeout=context.timeout, interval=context.interval)
    built_in = [item for item in items if item["key"] in BUILT_IN_SOURCES]
    problems = [problem for item in built_in for problem in _source_problems(item)]
    if problems:
        raise StepFailedError("; ".join(problems))
    probe = _fetch(product, NO_SOURCE)
    if probe.status_code == 404:
        raise StepFailedError(
            "crawling is on in this product (a fetch of a key no source has got to the source "
            "lookup): the check never fetches a live regulator site, so it starts no crawl; "
            "make product runs with CW_PIPELINE_CRAWL_ENABLED=false"
        )
    if (probe.status_code, problem_slug(probe)) != (503, CRAWL_DISABLED):
        raise StepFailedError(
            f"POST {SOURCES}/{NO_SOURCE}/fetch answered {describe(probe)}, not 503 {CRAWL_DISABLED}"
        )
    before = _latest_runs(product)
    refused = _fetch(product, FETCHED_SOURCE)
    if refused.status_code == 202:
        raise StepFailedError(f"a crawl of {FETCHED_SOURCE} started: crawling must stay off")
    if (refused.status_code, problem_slug(refused)) != (503, CRAWL_DISABLED):
        raise StepFailedError(
            f"POST {SOURCES}/{FETCHED_SOURCE}/fetch answered {describe(refused)}, not 503 "
            f"{CRAWL_DISABLED}"
        )
    if _latest_runs(product) != before:
        raise StepFailedError(f"the refused fetch of {FETCHED_SOURCE} recorded a crawl run")
    hidden = product.public.get(SOURCES)
    if (hidden.status_code, problem_slug(hidden)) != (404, ROUTE_NOT_FOUND):
        raise StepFailedError(
            f"GET {SOURCES} on the public listener answered {hidden.status_code}, not 404"
        )
    standing = ", ".join(f"{item['key']} {item['status']}" for item in built_in)
    others = len(items) - len(built_in)
    return [
        f"sources: the {len(built_in)} built-in ones listed ({standing})"
        + (f", and {others} more" if others else ""),
        f"fetch refused while crawling is off: 503 {CRAWL_DISABLED}, no crawl run recorded",
        f"GET {SOURCES} on the public listener: 404 {ROUTE_NOT_FOUND}",
        "a crawl over recorded fixtures: not configured in the product, which never fetches; "
        "test_pipeline_crawl_flow.py runs one",
        *_uploads_and_tasks(product, built_in),
    ]


def _uploads_and_tasks(product: Product, built_in: Sequence[Mapping[str, Any]]) -> list[str]:
    """The statutes are upload-only, the task queue answers, and an upload of a file that is no
    document is refused with nothing stored."""
    listable = [
        item["key"]
        for item in built_in
        if item["key"] in STATUTE_SOURCES and item.get("listable") is not False
    ]
    if listable:
        raise StepFailedError(f"the statute sources must be upload-only: {', '.join(listable)}")
    queue = ok(product.internal.get(TASKS, params={"status": "open"}))["items"]
    target = STATUTE_SOURCES[1]

    def count() -> int:
        items = ok(product.internal.get(SOURCES))["items"]
        return next(int(item["document_count"]) for item in items if item["key"] == target)

    before = count()
    refused = product.internal.post(
        f"{SOURCES}/{target}/uploads",
        files={"file": ("check.txt", b"cw-product check: no document", "text/plain")},
        data={"actor_id": str(FETCH_ACTOR), "reason": UPLOAD_REASON},
        headers=product.write_headers(),
    )
    if (refused.status_code, problem_slug(refused)) != (415, UPLOAD_UNSUPPORTED):
        raise StepFailedError(
            f"POST {SOURCES}/{target}/uploads answered {describe(refused)}, not 415 "
            f"{UPLOAD_UNSUPPORTED}"
        )
    if count() != before:
        raise StepFailedError(f"the refused upload stored a document under {target}")
    return [
        f"statutes upload-only: {', '.join(STATUTE_SOURCES)}",
        f"GET {TASKS}?status=open: {len(queue)} open on the first page",
        f"an upload that is no document refused: 415 {UPLOAD_UNSUPPORTED}, nothing stored",
    ]


# ---------------------------------------------------------------- extraction


def gateway_provider(product: Product) -> str:
    """The model provider the product's gateway answers from (``CW_LLM_PROVIDER``), as the
    product's app reads its settings."""
    settings = service_settings(
        entry_named("llm-gateway"), product.settings, internal_url=product.internal_url
    )
    provider: str = settings.llm_provider
    return provider


def extraction(context: CheckContext) -> list[str]:
    product = context.product
    provider = gateway_provider(product)
    if provider != "fake":
        raise StepSkippedError(
            f"the product's gateway answers from {provider}, not its fake model: the check asks "
            "no real model"
        )
    queue = ok(product.internal.get(TASKS, params={"kind": "triage"}))["items"]
    if any(item.get("kind") != "triage" for item in queue):
        raise StepFailedError(f"GET {TASKS}?kind=triage listed a task of another kind")
    nobody = f"{TASKS}/{uuid4()}/resolve"
    decision = {
        "actor_id": str(FETCH_ACTOR),
        "reason": TRIAGE_REASON,
        "triage": {"relevance": "relevant", "doc_type": "notification"},
    }
    missing = product.internal.post(nobody, json=decision, headers=product.write_headers())
    if (missing.status_code, problem_slug(missing)) != (404, TASK_NOT_FOUND):
        raise StepFailedError(
            f"a triage of a task nobody opened answered {describe(missing)}, not 404 "
            f"{TASK_NOT_FOUND}"
        )
    untyped = product.internal.post(
        nobody,
        json={**decision, "triage": {"relevance": "relevant"}},
        headers=product.write_headers(),
    )
    if (untyped.status_code, problem_slug(untyped)) != (422, REQUEST_INVALID):
        raise StepFailedError(
            f"a relevant triage without a type answered {describe(untyped)}, not 422 "
            f"{REQUEST_INVALID}"
        )
    stage = RuleExtractionStage(
        LlmRuleExtractor(
            GatewayProvider(client=product.internal), load_prompt(*RULE_PROMPT), load_ontology()
        )
    )
    context_of_call = ExtractionContext(
        regulator="CBIC",
        prompt_version=RULE_PROMPT_REF,
        model="llm-gateway",
        ontology_version=ONTOLOGY_VERSION,
    )
    try:
        got = stage.run(EXTRACTION_DOCUMENT, context_of_call)
    except GatewayError as exc:
        raise StepFailedError(f"the gateway refused the extraction's ask: {exc}") from exc
    if got.fields is None:
        read = (
            f"not a candidate twice ({'; '.join(i.detail for i in got.report.issues)}), so it "
            "would be stored unparseable for an analyst"
        )
    else:
        read = f"a candidate with {len(got.report.issues)} issue(s) for review"
    return [
        f"GET {TASKS}?kind=triage: {len(queue)} on the first page",
        f"a triage of a task nobody opened: 404 {TASK_NOT_FOUND}; a relevant one without a "
        f"type: 422 {REQUEST_INVALID}",
        f"the extraction asked the gateway's fake model {got.attempts} time(s) with "
        f"{RULE_PROMPT_REF} about a synthetic notification: {read}",
        "nothing ingested, uploaded or stored: test_extraction_flow.py and the pipeline's "
        "extraction workflow tests extract from a recorded notification",
    ]


# ---------------------------------------------------------------- review


def review_queue(product: Product) -> list[dict[str, Any]]:
    """Every review task, a page at a time, in the queue's order."""
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, str | int] = {"limit": 200}
        if cursor is not None:
            params["cursor"] = cursor
        page = ok(product.internal.get(REVIEW_TASKS, params=params))
        items += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            return items


def seed_drafts(context: CheckContext) -> dict[str, str]:
    """The seed calendar's versions that are drafts needing review, by version id."""
    drafts: dict[str, str] = {}
    for rule in load_calendar(load_ontology()).rules:
        versions = poll(
            partial(rule_versions, context.product, rule.rule_key),
            timeout=context.timeout,
            interval=context.interval,
        )
        for version in versions:
            if version["status"] == "draft" and version["seed_status"] == NEEDS_REVIEW:
                drafts[str(version["rule_version_id"])] = f"{rule.rule_key} v{version['version']}"
    return drafts


def review(context: CheckContext) -> list[str]:
    product = context.product
    headers = product.review_headers()
    opened = ok(product.internal.post(f"{REVIEW_TASKS}/seed", headers=headers))
    again = ok(product.internal.post(f"{REVIEW_TASKS}/seed", headers=headers))
    if again["opened"]:
        raise StepFailedError(
            f"a second seed request opened {again['opened']} more tasks: one per draft, once"
        )
    drafts = seed_drafts(context)
    tasks = review_queue(product)
    waiting = [task for task in tasks if task["status"] in WAITING]
    tasked = {str(task["rule_version_id"]) for task in waiting}
    untasked = sorted(label for version_id, label in drafts.items() if version_id not in tasked)
    if untasked:
        raise StepFailedError(f"seed drafts with no task waiting: {', '.join(untasked)}")
    moved_on = sorted(
        f"{task['rule_key']} v{task['version']} ({task['version_status']})"
        for task in waiting
        if task["version_status"] not in IN_REVIEW_FLOW
    )
    claimed, claim_line = claim_one(product, waiting)
    lines = [
        f"seed tasks: {opened['opened']} opened now, a second request opened none",
        f"waiting: {len(waiting)} tasks (of {len(tasks)}), every one of the {len(drafts)} "
        "seed drafts that need review among them",
    ]
    if moved_on:
        lines.append(
            "waiting on versions the publish routes moved on (decide them with reject): "
            + ", ".join(moved_on)
        )
    lines.append(claim_line)
    if claimed is not None:
        lines.append(read_task(product, claimed))
    stats = ok(product.internal.get(REVIEW_STATS))
    counted = stats["by_status"]["open"] + stats["by_status"]["claimed"]
    if counted < len(waiting) or stats["oldest_open_age_seconds"] < 0:
        raise StepFailedError(f"the stats count {counted} waiting tasks, the queue {len(waiting)}")
    lines.append(
        f"stats: {stats['by_status']['open']} open, {stats['by_status']['claimed']} claimed, "
        f"{stats['by_status']['decided']} decided; the oldest has waited "
        f"{stats['oldest_open_age_seconds'] / 3600:.1f} h"
    )
    hidden = product.public.get(REVIEW_TASKS)
    if (hidden.status_code, problem_slug(hidden)) != (404, ROUTE_NOT_FOUND):
        raise StepFailedError(
            f"GET {REVIEW_TASKS} on the public listener answered {hidden.status_code}, not 404"
        )
    lines.append(f"GET {REVIEW_TASKS} on the public listener: 404 {ROUTE_NOT_FOUND}")
    return lines


def claim_one(
    product: Product, waiting: Sequence[Mapping[str, Any]]
) -> tuple[Mapping[str, Any] | None, str]:
    """The task the check analyst holds, or the first open one, claimed (again) by the check
    analyst; the claimant claiming again changes nothing."""
    analyst = str(CHECK_ANALYST.user_id)
    held = [
        task
        for task in waiting
        if task["claimed_by"] == analyst and task["version_status"] in IN_REVIEW_FLOW
    ]
    candidates = held or [
        task for task in waiting if task["status"] == "open" and task["version_status"] == "draft"
    ]
    if not candidates:
        return None, "claim: every waiting draft is claimed by someone else, so none was claimed"
    task = candidates[0]
    path = f"{REVIEW_TASKS}/{task['task_id']}/claim"
    body = {"actor_id": analyst}
    claimed = ok(product.internal.post(path, json=body, headers=product.review_headers()))
    if (claimed["status"], claimed["claimed_by"]) != ("claimed", analyst):
        raise StepFailedError(f"the claim of task {task['task_id']} answered {claimed}")
    repeated = ok(product.internal.post(path, json=body, headers=product.review_headers()))
    if repeated["claimed_at"] != claimed["claimed_at"]:
        raise StepFailedError("claiming a task the analyst holds changed the claim")
    how = "held from an earlier run" if held else "claimed now"
    return claimed, (
        f"claim: {task['rule_key']} v{task['version']} ({how}) by {CHECK_ANALYST.name}; "
        "claiming again changed nothing"
    )


def read_task(product: Product, task: Mapping[str, Any]) -> str:
    detail = ok(product.internal.get(f"{REVIEW_TASKS}/{task['task_id']}"))
    version = detail["rule_version"]
    problems: list[str] = []
    if detail["task"]["task_id"] != task["task_id"]:
        problems.append("another task came back")
    if version["rule_version_id"] != task["rule_version_id"]:
        problems.append("another version came back")
    if not detail["specification_described"]:
        problems.append("its specification is not described")
    if task["task_id"] not in {entry["task_id"] for entry in detail["tasks"]}:
        problems.append("its history leaves it out")
    if problems:
        raise StepFailedError(f"task {task['task_id']}: " + "; ".join(problems))
    verified = sum(citation["verified"] for citation in detail["citations"])
    return (
        f"read: {version['rule_key']} v{version['version']} ({version['status']}, "
        f"{version['seed_status']}), {len(detail['specification_described'])} lines of "
        f"specification, {len(detail['citations'])} citations ({verified} verified), "
        f"{len(detail['decisions'])} decisions and {len(detail['tasks'])} tasks in its history"
    )


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
    Step(
        "reminders",
        "the sweep run a few days before a due date sends a reminder through the sink",
        reminders,
    ),
    Step(
        "rollback",
        "a withdrawn rule closes its obligations in both tenants and sends withdrawal notices",
        rollback,
    ),
    Step(
        "tracking",
        "a member starts, assigns, completes once with one key, reads and comments on a duty",
        tracking,
    ),
    Step(
        "changes",
        "the feed lists the publication, the impact its affected clients, a dry run its counts",
        changes,
    ),
    Step(
        "public",
        "the public listener lists obligations, answers a question and sends a bulk change card",
        public,
    ),
    Step(
        "sources",
        "the pipeline lists its sources, refuses a fetch while crawling is off and an upload "
        "that is no document",
        sources,
    ),
    Step(
        "review",
        "every seed draft waits in the review queue; one task is claimed and read, and the "
        "stats count them",
        review,
    ),
    Step(
        "extraction",
        "the triage routes answer and the rule extraction asks the gateway with the registered "
        "prompt, ingesting nothing",
        extraction,
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
        except StepSkippedError as exc:
            result.skipped, result.details = True, [str(exc)]
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
        mark = "skip  " if result.skipped else "ok    " if result.ok else "FAILED"
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
                "skipped": result.skipped,
            }
            for result in results
        ],
    }
