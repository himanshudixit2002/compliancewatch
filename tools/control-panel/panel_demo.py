"""The fake core behind ``panel_server.py --demo``: canned data and simulated runs.

It answers every route with realistic data and runs no program: no subprocess, no signal, no
network, no file written. A demo run streams made-up output step by step, at a believable pace,
and can be cancelled; when it finishes it changes the demo world (Start everything brings the
stack up, Stop everything takes it down), so the status follows what was run.

Error paths to try: seeding the product while it is stopped fails with "the product is not
answering"; the lint check fails with eslint's own lines; the checkout is on a branch, so the
confirms warn that it is not main; Claude's build agent is running make check, so the stops warn
that they break it.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Final

import panel_catalog as catalog
import panel_core as core

REPO: Final = Path("/Users/you/compliancewatch")
DEMO_PID: Final = 70000
AGENT_PIDS: Final = (61000, 61001, 61002, 61003)

MAKE_TARGETS: Final[tuple[tuple[str, str], ...]] = (
    ("help", "Show this help"),
    ("doctor", "Print which required tools are present"),
    ("dev", "Start Postgres, Redis, Redpanda, Temporal (+UI); waits for health, prints endpoints"),
    (
        "dev-observability",
        "Same as dev plus Langfuse, OTel collector, Prometheus, Tempo, Grafana (compose "
        "profile: observability)",
    ),
    ("dev-llm", "Build and start the fake LLM gateway container (compose profile: llm)"),
    ("dev-down", "Stop the stack, keep volumes"),
    (
        "dev-reset",
        "Stop the stack and delete volumes (infra/dev/postgres/init.sql runs again on "
        "next make dev)",
    ),
    ("dev-logs", "Tail logs; one service with SERVICE=postgres"),
    ("dev-ps", "Container status and health"),
    ("dev-psql", "psql into the application database"),
    ("dev-backup", "pg_dump the dev database into var/backups/<timestamp>.dump"),
    (
        "dev-restore",
        "Restore the dev database from a dump: make dev-restore FILE=var/backups/x.dump",
    ),
    ("compose-config", "Validate docker-compose.yml (CLI only, no daemon needed)"),
    ("py-sync", "Sync the Python workspace into .venv"),
    ("lock-check", "Fail if uv.lock is out of date with the pyproject files"),
    ("py-lint", "ruff check and ruff format --check"),
    ("py-format", "ruff format and ruff check --fix"),
    (
        "py-typecheck",
        "mypy --strict per package (src, tests, migrations/env.py), the root conftest and"
        " the repo scripts",
    ),
    ("py-test", "pytest: unit and contract tests with the coverage gate (no Docker needed)"),
    ("py-test-integration", "testcontainers tests; skipped gracefully when Docker is absent"),
    ("importlint", "import-linter contracts: no cross-service imports, domain imports no I/O"),
    ("ts-install", "pnpm install --frozen-lockfile"),
    ("ts-lint", "eslint per package (turbo, cached) + prettier check"),
    ("ts-format", "prettier --write"),
    ("ts-typecheck", "tsc --noEmit (strict) per package via turbo"),
    ("ts-test", "vitest run --coverage per package (thresholds in each vitest.config)"),
    ("ts-build", "next build + tsc build"),
    ("ts-dev", "next dev (:3000) and whatsapp-bot (:8080) with reload"),
    ("install", "Install both toolchains"),
    ("lint", "Lint both sides (CI step 1)"),
    ("format", "Auto-format both sides"),
    ("typecheck", "mypy --strict and tsc --strict (CI step 1)"),
    ("test", "Unit and contract tests on both sides (CI step 2)"),
    ("check", "Everything CI runs before integration tests (the gates listed in CHECKS)"),
    ("runbooks-check", "Every Prometheus alert links an existing runbook (guide section 18)"),
    (
        "eval",
        "Eval harness against evals/golden: make eval [EVAL_PROFILE=ci|nightly] "
        '[ARGS="--provider fake --suite qa"]',
    ),
    (
        "eval-check",
        "KAG golden set and world well formed: quotes, seed supports, scripted plans and answers",
    ),
    (
        "demo",
        "The demo tenant end to end in one process (consent, profile, rules, obligations,"
        " reminder): make demo [ARGS=--json]",
    ),
    (
        "label",
        'Labelling tool: make label ARGS="check" | "index --source cbic_notifications '
        '--since 2024-01-01 --out evals/golden/extraction/cbic_notifications/index.yaml" '
        '| "prepare --index ..."',
    ),
    ("migrate", "alembic upgrade head for every service, or one: make migrate SERVICE=identity"),
    ("run", "Run one service with reload: make run SERVICE=identity [PORT=8001]"),
    (
        "seed",
        "Load the rulebook seed calendar as draft rule versions: make seed "
        "SERVICE=rulebook [ARGS=--check]",
    ),
    (
        "backfill",
        "Backfill one regulator source into var/raw: make backfill SERVICE=pipeline "
        'ARGS="--source cbic_notifications --since 2026-01-01"',
    ),
    (
        "golden-export",
        "Decided rule candidates as draft golden cases: make golden-export "
        'ARGS="--since 2026-10-01 --out var/golden-export"',
    ),
    (
        "crawl-report",
        "Crawl runs, failures, gaps and detection delays per source, and the F1 check: "
        'make crawl-report [ARGS="--days 30 --json"]',
    ),
    (
        "extract-backlog",
        "The classified backlog per source, and a sweep that extracts it: make extract-backlog "
        '[ARGS="--dry-run --source cbic_notifications --limit 200 --json"]',
    ),
    (
        "worker",
        "Run a service's worker process, python -m <pkg>.worker (consumers, relay, "
        "periodic jobs, Temporal): make worker SERVICE=pipeline",
    ),
    ("relay", "Run the outbox relay for one service's schema: make relay SERVICE=obligation"),
    (
        "replay",
        "List a dead-letter topic, or send one message back to its origin: make replay "
        'ARGS="list --topic <topic>.<group>.dlq" | ARGS="send --topic <dlq> --event-id <id> '
        '[--dry-run]"',
    ),
    (
        "openapi",
        "Export a service's OpenAPI spec: make openapi SERVICE=llm-gateway -> "
        "packages/contracts/openapi/<svc>.v1.json",
    ),
    (
        "contracts",
        "Generate the event clients (pydantic + TypeScript) and the Python REST models "
        "(openapi/clients.json)",
    ),
    (
        "contracts-check",
        "Event schemas pass the 2020-12 metaschema, every topic in code has one, the "
        "generated clients match them, and public.v1.json is current",
    ),
    ("hooks", "Install the pre-commit and commit-msg hooks"),
    ("ci-lint", "Validate GitHub Actions workflows and the pre-commit config without running them"),
    (
        "migrations-check",
        "Migration files: one head per service, names match revisions, downgrades, marked"
        " contract steps",
    ),
    (
        "migrations-catalog",
        "After make migrate: tenant tables have forced row-level security (rules in "
        "infra/scripts/migration_lint.toml)",
    ),
    (
        "alerts-check",
        "promtool: alert rules parse and their unit tests pass "
        "(infra/dev/prometheus/alerts.test.yml)",
    ),
    ("openapi-check", "Every service that serves API routes commits its spec and a contract test"),
    (
        "openapi-compat",
        "Committed specs break no client of a base ref: make openapi-compat [BASE=origin/main]",
    ),
    (
        "sast",
        "Semgrep: registry packs and the rules in .semgrep; an ERROR finding fails "
        "(writes semgrep.sarif)",
    ),
    (
        "deps-scan",
        "Trivy: fixable HIGH and CRITICAL vulnerabilities and misconfigurations (settings"
        " in .trivy.yaml)",
    ),
    ("ci-gate-check", 'Every ci.yml job is in the needs of the required "CI gate" job'),
    (
        "data-quality",
        "Rulebook data-quality checks on the local rulebook schema, or "
        "CW_DQ_DATABASE_URL: make data-quality [ARGS=--json]",
    ),
    ("flags", "Write py-common's copy of the flag registry, then run flags-check"),
    (
        "flags-check",
        "Flag registry: schema, owners, expiry, bool defaults off, py-common copy "
        "current, every switch in settings registered",
    ),
    (
        "dev-flags",
        "Start Unleash for CW_FLAGS_PROVIDER=unleash (compose profile: flags); creates "
        "its database when missing",
    ),
    (
        "openapi-public",
        "Merge the operations the services tag public into "
        "packages/contracts/openapi/public.v1.json (after make openapi SERVICE=x), then "
        "regenerate the Python REST models",
    ),
    (
        "web-dev",
        "next dev on WEB_PORT from .env; /admin lists the internal tools, /design the UI kit",
    ),
    (
        "web-stack",
        "UI-only stack, no worker: every service on SERVICE_PORT_BASE+1..10 with memory "
        "stores (pids and logs in var/web-stack): make web-stack [STORE=postgres] "
        "[BILLING=memory]",
    ),
    (
        "web-stack-wait",
        "Wait until every web-stack service answers /health (WEB_STACK_WAIT_SECONDS, default 60)",
    ),
    (
        "web-stack-down",
        "Stop the web-stack services and remove their pid files (logs stay in var/web-stack)",
    ),
    (
        "control-panel",
        "Open ComplianceWatch Control in your browser (tools/control-panel); Ctrl-C stops it",
    ),
    (
        "control-panel-app",
        "Build ComplianceWatch.app on the Desktop: make control-panel-app [DEST=~/Applications]",
    ),
    (
        "web-stack-logs",
        "Tail a web-stack service's log: make web-stack-logs SERVICE=identity (every log "
        "without SERVICE)",
    ),
    (
        "web-seed",
        "Seed the web-stack services with the demo tenant and a recorded notification: "
        'make web-seed [ARGS="--tenant <uuid> --json"]',
    ),
    (
        "web-e2e-install",
        "Download Chromium for Playwright, once per machine (the package has no install script)",
    ),
    (
        "web-e2e",
        "Build the web app and run Playwright with axe against next start on WEB_PORT and"
        " the web-stack services (after make web-stack-wait and make web-seed)",
    ),
    ("web-screens", "Regenerate docs/web/screens.md from the screen registry"),
    ("web-screens-check", "docs/web/screens.md matches the screen registry (part of make check)"),
    (
        "openapi-ts",
        "Generate TypeScript types from packages/contracts/openapi into clients/typescript/openapi",
    ),
    (
        "openapi-ts-check",
        "The generated OpenAPI types match the committed specs (part of make check)",
    ),
    (
        "product",
        "The local product: make dev, make migrate, the seed calendar, cw-mvp serve and "
        "worker (Kafka, Temporal on), next dev on WEB_PORT (3000): make product [WEB=0] "
        "[WEB_PORT=3400]",
    ),
    (
        "product-role",
        "Create or refresh PRODUCT_DB_USER, the product's role under row-level security, "
        "on the running Postgres (after make migrate)",
    ),
    (
        "product-wait",
        "Wait for the product: the internal listener ready, the worker healthy and the "
        "web app answering (PRODUCT_WAIT_SECONDS, default 120)",
    ),
    (
        "product-seed",
        "Fill the running product: synthetic tenants, the demo publication, first "
        'decisions (cw-product seed): make product-seed [ARGS="--rule gstr9_annual '
        '--json"]',
    ),
    (
        "product-check",
        "Prove the running product works, step by step (cw-product check; exit 0 means "
        'accepted): make product-check [ARGS="--step loop --json"] [ARGS="--destructive"]'
        " (CI only)",
    ),
    (
        "product-e2e",
        "Build the web app and run the Playwright product project against the running "
        "product (after make product and make product-seed): make product-e2e "
        "[PRODUCT_E2E_PORT=3400]",
    ),
    (
        "product-down",
        "Stop the product's processes: only the pids make product recorded in "
        "var/product, with their children (logs stay)",
    ),
    (
        "product-logs",
        "Show a product process's log: make product-logs PROC=app|worker|web [FOLLOW=0]",
    ),
    (
        "mvp-image",
        "Build the one deployable's image (composition/mvp/Dockerfile) as MVP_IMAGE "
        "(compliancewatch-mvp:local)",
    ),
    (
        "product-image",
        "The local product from the image: make dev, the image, cw_app, cw-mvp release, "
        "serve and worker in containers, the seed calendar: make product-image "
        "[MVP_BUILD=0]",
    ),
    (
        "product-image-down",
        "Remove the image product's containers (mvp-release, mvp-app, mvp-worker); the "
        "dev stack keeps running",
    ),
    (
        "product-image-logs",
        "Show a container's log of the image product: make product-image-logs "
        "PROC=app|worker|release [FOLLOW=0]",
    ),
)


def demo_project() -> core.Project:
    """The demo checkout: main's Makefile targets, default ports, the fallback screens."""
    return core.Project(
        repo=REPO,
        env=core.program_env({"PATH": "/usr/bin:/bin", "HOME": "/Users/you"}),
        ports=core.resolve_ports({}, {}),
        make_targets=dict(MAKE_TARGETS),
        checks=list(core.CI_ORDER[:7]),
        check_steps=list(core.CHECK_STEPS_FALLBACK),
        screens=list(core.SCREENS_FALLBACK),
        workers=["rulebook", "applicability-engine", "obligation", "notification", "pipeline"],
        relays=[
            "identity",
            "profile",
            "rulebook",
            "applicability-engine",
            "obligation",
            "notification",
            "eval",
            "pipeline",
        ],
        volumes=[
            (f"compliancewatch_{name}", name)
            for name in (
                "postgres_data",
                "redis_data",
                "redpanda_data",
                "prometheus_data",
                "tempo_data",
                "grafana_data",
            )
        ],
    )


PRODUCT_PARTS: Final = ("internal", "public", "worker", "web")


@dataclass(frozen=True)
class Failure:
    """A failure the next run of ``action`` meets at step ``step`` (``POST /api/demo/state``)."""

    action: str
    step: int = 0
    state: core.StepState = "failed"
    lines: tuple[str, ...] = ()


@dataclass
class World:
    """What runs in the demo: changed by the demo runs and ``POST /api/demo/state``, read by the
    demo probes."""

    docker: bool = True
    infra: bool = True
    observability: bool = False
    services: int = len(core.SERVICES)
    web: bool = True
    product: set[str] = field(default_factory=set)
    workers: set[str] = field(default_factory=set)
    relays: set[str] = field(default_factory=set)
    backups: list[core.Dump] = field(default_factory=list)
    branch: str = "demo-branch"
    dirty: int = 0
    sessions: str = "agent"
    """Who runs make check in the checkout besides this app: ``agent`` (Claude's build agent,
    never stopped from here), ``terminal`` (a person's terminal) or ``none``."""
    mishaps: bool = True
    failure: Failure | None = None
    speed: float = 1.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def take_failure(self, action_id: str, step: int) -> Failure | None:
        """The armed failure, once, when it is for this action's step."""
        with self.lock:
            failure = self.failure
            if failure is None or failure.action != action_id or failure.step != step:
                return None
            self.failure = None
            return failure

    def describe(self) -> dict[str, Any]:
        with self.lock:
            return {
                "docker": self.docker,
                "infra": self.infra,
                "tools": self.observability,
                "services": self.services,
                "web": self.web,
                "product": {part: part in self.product for part in PRODUCT_PARTS},
                "workers": sorted(self.workers),
                "relays": sorted(self.relays),
                "branch": self.branch,
                "dirty": self.dirty,
                "sessions": self.sessions,
                "mishaps": self.mishaps,
                "speed": self.speed,
                "fail_next": None
                if self.failure is None
                else {
                    "action": self.failure.action,
                    "step": self.failure.step,
                    "state": self.failure.state,
                    "lines": list(self.failure.lines),
                },
            }


# ---- POST /api/demo/state: the world a UI test asks for -----------------------------------------

MISSING: Final = object()
"""A key the body leaves out (``fail_next: null`` clears the armed failure; leaving it out keeps
it)."""

_BRANCH: Final = re.compile(r"[A-Za-z0-9._/-]{1,100}")
MAX_FAILURE_LINES: Final = 200


@dataclass(frozen=True)
class StateChange:
    world: Mapping[str, Any]
    failure: Failure | None
    set_failure: bool
    speed: float | None


def _flag(name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise catalog.ParamError(f"world.{name} must be true or false")
    return value


def _names(name: str, value: object, allowed: Collection[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise catalog.ParamError(f"world.{name} must be a list of names")
    if unknown := sorted(set(value) - set(allowed)):
        raise catalog.ParamError(f"world.{name}: unknown {', '.join(unknown)}")
    return list(value)


def parse_world(raw: object, project: core.Project) -> dict[str, Any]:
    """``world`` of the body as World fields. The keys are the UI mock's: ``services`` is how
    many of the ten answer (or true/false), ``product`` a part map (merged) or true/false,
    ``tools`` the observability containers, ``sessions`` "agent", "terminal" or "none"."""
    if raw is MISSING or raw is None:
        return {}
    if not isinstance(raw, dict):
        raise catalog.ParamError("world must be an object")
    known = {
        "docker",
        "infra",
        "tools",
        "observability",
        "services",
        "web",
        "product",
        "workers",
        "relays",
        "background",
        "branch",
        "dirty",
        "sessions",
        "mishaps",
        "demo",
    }
    if unknown := sorted(set(raw) - known):
        raise catalog.ParamError(f"unknown world keys: {', '.join(unknown)}")
    out: dict[str, Any] = {}
    for name in ("docker", "infra", "web", "mishaps"):
        if name in raw:
            out[name] = _flag(name, raw[name])
    for name in ("tools", "observability"):
        if name in raw:
            out["observability"] = _flag(name, raw[name])
    if "services" in raw:
        value = raw["services"]
        count = len(core.SERVICES)
        if isinstance(value, bool):
            value = count if value else 0
        if not isinstance(value, int) or not 0 <= value <= count:
            raise catalog.ParamError(f"world.services must be 0 to {count}, or true or false")
        out["services"] = value
    if "product" in raw:
        value = raw["product"]
        if isinstance(value, bool):
            out["product"] = dict.fromkeys(PRODUCT_PARTS, value)
        elif isinstance(value, dict):
            if unknown := sorted(set(value) - set(PRODUCT_PARTS)):
                raise catalog.ParamError(f"unknown product parts: {', '.join(unknown)}")
            out["product"] = {part: _flag(f"product.{part}", on) for part, on in value.items()}
        else:
            raise catalog.ParamError("world.product must be true, false or a map of its parts")
    if "workers" in raw:
        out["workers"] = _names("workers", raw["workers"], project.workers)
    if "relays" in raw:
        out["relays"] = _names("relays", raw["relays"], project.relays)
    if "background" in raw:
        value = raw["background"]
        if not isinstance(value, dict):
            raise catalog.ParamError("world.background must be a map of worker-/relay- keys")
        running = [key for key, pid in value.items() if pid]
        keys = {spec.key for spec in project.backgrounds()[1:]}
        if unknown := sorted(set(value) - keys):
            raise catalog.ParamError(f"unknown background keys: {', '.join(unknown)}")
        out["workers"] = [key.split("-", 1)[1] for key in running if key.startswith("worker-")]
        out["relays"] = [key.split("-", 1)[1] for key in running if key.startswith("relay-")]
    if "branch" in raw:
        value = raw["branch"]
        if not isinstance(value, str) or not _BRANCH.fullmatch(value):
            raise catalog.ParamError("world.branch must be a branch name")
        out["branch"] = value
    if "dirty" in raw:
        value = raw["dirty"]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100_000:
            raise catalog.ParamError("world.dirty must be a count")
        out["dirty"] = value
    if "sessions" in raw:
        value = raw["sessions"]
        if isinstance(value, list):
            value = "agent" if value else "none"
        if isinstance(value, bool):
            value = "agent" if value else "none"
        if value not in ("agent", "terminal", "none"):
            raise catalog.ParamError('world.sessions must be "agent", "terminal" or "none"')
        out["sessions"] = value
    return out


def parse_failure(raw: object, actions: Collection[str]) -> Failure | None:
    """``fail_next``: the next run of ``action`` prints ``lines`` at step ``step`` (0 first) and
    ends there ``failed`` or ``timeout``; null clears it."""
    if raw is MISSING or raw is None:
        return None
    if not isinstance(raw, dict):
        raise catalog.ParamError("fail_next must be an object or null")
    if unknown := sorted(set(raw) - {"action", "step", "state", "lines", "error"}):
        raise catalog.ParamError(f"unknown fail_next keys: {', '.join(unknown)}")
    action = raw.get("action")
    if not isinstance(action, str) or action not in actions:
        raise catalog.ParamError("fail_next.action must be an action id")
    step = raw.get("step", 0)
    if isinstance(step, bool) or not isinstance(step, int) or not 0 <= step < 100:
        raise catalog.ParamError("fail_next.step must be a step index (0 is the first)")
    state = raw.get("state", "failed")
    if state not in ("failed", "timeout"):
        raise catalog.ParamError('fail_next.state must be "failed" or "timeout"')
    lines = raw.get("lines", [])
    if (
        not isinstance(lines, list)
        or len(lines) > MAX_FAILURE_LINES
        or not all(isinstance(line, str) and len(line) <= 2000 for line in lines)
    ):
        raise catalog.ParamError(f"fail_next.lines must be up to {MAX_FAILURE_LINES} lines of text")
    return Failure(action, step, "timeout" if state == "timeout" else "failed", tuple(lines))


def parse_speed(raw: object) -> float | None:
    """``speed``: how much faster than the demo's own pace runs play (0.1 to 50)."""
    if raw is MISSING or raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not 0.1 <= raw <= 50:
        raise catalog.ParamError("speed must be a number from 0.1 to 50")
    return float(raw)


EFFECTS: Final[dict[str, Callable[[World], None]]] = {}


def effect(*titles: str) -> Callable[[Callable[[World], None]], Callable[[World], None]]:
    def register(fn: Callable[[World], None]) -> Callable[[World], None]:
        for title in titles:
            EFFECTS[title] = fn
        return fn

    return register


@effect("start everything")
def _start_everything(world: World) -> None:
    world.docker = world.infra = world.web = True
    world.services = len(core.SERVICES)


@effect("stop everything", "force-stop Docker", "stop Docker")
def _stop_everything(world: World) -> None:
    world.docker = world.infra = world.observability = world.web = False
    world.services = 0
    world.product.clear()
    world.workers.clear()
    world.relays.clear()


@effect("start Docker")
def _start_docker(world: World) -> None:
    world.docker = True


@effect("make dev")
def _start_infra(world: World) -> None:
    world.docker = world.infra = True


@effect("make dev-down")
def _stop_infra(world: World) -> None:
    world.infra = world.observability = False


@effect("make dev-observability")
def _start_observability(world: World) -> None:
    world.docker = world.infra = world.observability = True


@effect("start the UI-only stack", "restart the UI-only stack")
def _start_services(world: World) -> None:
    world.services = len(core.SERVICES)


@effect("stop the UI-only stack")
def _stop_services(world: World) -> None:
    world.services = 0


@effect("start the web app")
def _start_web(world: World) -> None:
    world.web = True


@effect("stop the web app")
def _stop_web(world: World) -> None:
    world.web = False


@effect("start the product")
def _start_product(world: World) -> None:
    world.docker = world.infra = True
    world.product = set(PRODUCT_PARTS)


@effect("stop the product")
def _stop_product(world: World) -> None:
    world.product.clear()


@effect("make dev-backup")
def _backup(world: World) -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    world.backups.insert(0, core.Dump(f"var/backups/{stamp}.dump", 48_211_337, time.time()))


def _now_dumps() -> list[core.Dump]:
    now = time.time()
    return [
        core.Dump("var/backups/20261006-091512.dump", 47_902_114, now - 5 * 3600),
        core.Dump("var/backups/20261005-183044.dump", 46_118_903, now - 20 * 3600),
    ]


# ---- what demo steps print ---------------------------------------------------------------------

SERVICE_PIDS: Final = {name: 41201 + index for index, name in enumerate(core.SERVICES)}


type Out = Sequence[tuple[str, str | None]]


def step_lines(label: str) -> Out:
    """Made-up output for one step, by what its label says it does."""
    services = core.SERVICES
    if label == "start Docker":
        return [
            ("INFO[0000] starting colima", None),
            ("INFO[0000] runtime: docker", None),
            ("INFO[0011] starting ...                             context=vm", None),
            ("INFO[0029] provisioning ...                         context=docker", None),
            ("INFO[0033] starting ...                             context=docker", None),
            ("INFO[0036] done", None),
        ]
    if label in ("start databases and queues", "make dev"):
        lines: list[tuple[str, str | None]] = [
            (f" Container compliancewatch-{n}-1  Started", None) for n in core.INFRA
        ]
        lines += [(f" {n}: healthy", "ok") for n in core.INFRA]
        lines.append(
            (
                "Postgres on localhost:5432, Redpanda on localhost:19092, Temporal UI on "
                "http://localhost:8233",
                None,
            )
        )
        return lines
    if label in ("migrate databases", "make migrate"):
        lines = []
        for name in services:
            lines.append((f"alembic upgrade head ({name})", None))
            lines.append(
                (
                    f"INFO  [alembic.runtime.migration] Running upgrade -> {name[:4]}0007, "
                    "add the review columns",
                    None,
                )
            )
        return lines
    if label in ("start services", "make web-stack STORE=postgres"):
        return [
            (f"{name}: started (pid {SERVICE_PIDS[name]}), log var/web-stack/{name}.log", None)
            for name in services
        ]
    if label in ("wait for services", "make web-stack-wait"):
        return [(f"{name}: up", "ok") for name in services]
    if label == "start web app":
        return [
            ("web app starting on http://localhost:3000 (next dev)", None),
            ("  ▲ Next.js 16.3.8 · ready in 6.2s", None),
            ("web app ready on http://localhost:3000", "ok"),
        ]
    if label.startswith("open "):
        return [(f"opened {label[5:]} in your browser", None)]
    if label == "stop web app":
        return [
            ("tree of pid 76165 (pnpm --filter web dev, panel web app): 76165, 76174, 76180", None),
            ("stopped", "ok"),
        ]
    if label in ("stop the UI-only stack", "make web-stack-down", "stop services"):
        return [(f"  {name} stopped (pid {SERVICE_PIDS[name]})", None) for name in services]
    if label in ("stop the product's processes", "make product-down"):
        return [
            ("  web was not running", None),
            ("  worker stopped (pid 8675)", None),
            ("  app stopped (pid 8662)", None),
        ]
    if label == "stop the panel's workers and relays":
        return [("no worker or relay of this app is running", None)]
    if label in ("stop the dev stack's containers (make dev-down)", "make dev-down"):
        lines = [(f" Container compliancewatch-{n}-1  Stopping", None) for n in core.INFRA]
        lines += [(f" Container compliancewatch-{n}-1  Removed", None) for n in core.INFRA]
        lines.append((" Network compliancewatch_default  Removed", None))
        return lines
    if label.startswith("stop Docker") or label.startswith("force-stop Docker"):
        return [
            ('time="2026-10-06T19:10:00+05:30" level=info msg="stopping colima"', None),
            ('time="2026-10-06T19:10:04+05:30" level=info msg="stopping ..." context=docker', None),
            ('time="2026-10-06T19:10:09+05:30" level=info msg="stopping ..." context=vm', None),
            ('time="2026-10-06T19:10:12+05:30" level=info msg=done', None),
        ]
    if label == "lint":
        return [
            ("ruff check: All checks passed!", None),
            ("ruff format --check: 1214 files already formatted", None),
            ("pnpm turbo run lint", None),
            ("apps/web/src/app/admin/page.tsx", None),
            (
                "  12:7  error  'unused' is assigned a value but never used  "
                "@typescript-eslint/no-unused-vars",
                "err",
            ),
            ("✖ 1 problem (1 error, 0 warnings)", "err"),
            ("make: *** [ts-lint] Error 1", "err"),
        ]
    if label == "check the product answers":
        return [
            (
                "error: the product does not answer http://127.0.0.1:8080/ready; make product-seed "
                "runs only against the running product, so start it first",
                "err",
            ),
        ]
    if label.startswith("make product-check"):
        return [
            (f"✓ {step}: proved", "ok") for step in core.selectable_steps(core.CHECK_STEPS_FALLBACK)
        ]
    if label.startswith("make product WEB_PORT"):
        return [
            ("make dev: the databases are healthy", None),
            ("make migrate: every service is at head", None),
            ("cw-mvp serve: internal :8080, public :8000", None),
            ("cw-mvp worker: 23 loops, 3 task queues", None),
            ("next dev on http://127.0.0.1:3400", None),
            ("the product is ready", "ok"),
        ]
    if label == "make extract-backlog ARGS=--dry-run":
        return [
            ("# Classified backlog (rule_extraction@v3)", None),
            ("| Source | Waiting |", None),
            ("| cbic_notifications | 41 |", None),
            ("| gst_council | 7 |", None),
            ("48 document(s) wait as classified; the extraction is on.", "ok"),
        ]
    if label == "make extract-backlog":
        return [
            ("48 document(s) wait as classified; the extraction is on.", None),
            ("started pipeline-extract-backlog-5f0c2a: 48 document(s), 3 at a time", "ok"),
        ]
    if label.startswith("make dev-backup") or label == "back up the database first":
        return [("pg_dump compliancewatch into var/backups", None), ("47.9 MB written", "ok")]
    if label in WEB_CHECK_LINES:
        return WEB_CHECK_LINES[label]()
    return [(f"{label}: working…", None), (f"{label}: done", "ok")]


CHECK_PIDS: Final = {name: 47201 + index for index, name in enumerate(core.SERVICES)}
_CHECK_PORTS: Final = core.web_check_ports()
_CHECK_SPAN: Final = f"{_CHECK_PORTS[0]} to {_CHECK_PORTS[-2]} and {_CHECK_PORTS[-1]}"


def _check_ready() -> Out:
    return [
        (
            "Playwright's own Chromium is not downloaded here, so the browser tests use your "
            "installed Google Chrome",
            None,
        ),
        ("no test copy is running", None),
        (f"ports {_CHECK_SPAN} are free", "ok"),
    ]


def _check_start() -> Out:
    lines: list[tuple[str, str | None]] = [
        (
            f"web stack: services on {_CHECK_PORTS[0]}-{_CHECK_PORTS[-2]}, memory stores, billing "
            "provider none, rulebook publishing on",
            None,
        )
    ]
    lines += [
        (f"  {name}  {core.web_check_url(name)}  (log {core.WEB_CHECK_DIR}/{name}.log)", None)
        for name in core.SERVICES
    ]
    lines.append(("Next: make web-stack-wait, then make web-seed", None))
    return lines


def _check_wait() -> Out:
    return [(f"  {name} healthy on {core.web_check_url(name)}", "ok") for name in core.SERVICES]


def _check_seed() -> Out:
    return [
        ("seeding tenant 5b9e0c3a-6f1d-4e2a-9c47-2d8f0a1b7e63 (owner synthetic)", None),
        ("identity      4 consents recorded", None),
        ("profile       Acme Traders Private Limited, GSTIN 29ABCDE1234F1Z5 pre-filled", None),
        ("notification  WhatsApp preference set; opt-in confirmation recorded", None),
        ("rulebook      CBIC notification 01/2026 recorded with its clauses", None),
        (f"state         ../../{core.WEB_CHECK_SEED}", "ok"),
    ]


def _check_click() -> Out:
    return [
        (f"web app built into apps/web/{core.WEB_CHECK_DIST_DIR}", None),
        ("   ▲ Next.js 16.3.8 (Turbopack)", None),
        (" ✓ Compiled successfully in 51s", "ok"),
        ("Running 212 tests using 5 workers", None),
        ("  ✓  [chromium] e2e/home.spec.ts: the home page names the product (1.4s)", None),
        ("  ✓  [chromium] e2e/sign-in.spec.ts: an owner signs in (2.2s)", None),
        ("  ✓  [chromium] e2e/a11y.spec.ts: every registered page passes axe (38.1s)", None),
        ("  ✓  [chromium] e2e/admin-sources.spec.ts: an upload lands on its source (3.9s)", None),
        ("  212 passed (4.8m)", "ok"),
    ]


def _check_stop() -> Out:
    return [(f"  {name} stopped (pid {CHECK_PIDS[name]})", None) for name in core.SERVICES]


WEB_CHECK_LINES: Final[Mapping[str, Callable[[], Out]]] = {
    "check that the test copy can start": _check_ready,
    "start a separate test copy of the services": _check_start,
    "wait until the test copy answers": _check_wait,
    "add made-up demo data to the test copy": _check_seed,
    "build the web app and click through it in a robot browser": _check_click,
    "stop the test copy": _check_stop,
}
"""What Click through the web app prints in the demo, by step."""


def scripted_failure(label: str, world: World) -> bool:
    """The demo's own error paths: the lint check fails while the world keeps its mishaps, and
    seeding fails while the product does not answer."""
    with world.lock:
        if label == "lint":
            return world.mishaps
        if label == "check the product answers":
            return "internal" not in world.product
    return False


class DemoRunner:
    """Plays a plan's steps with made-up output; cancel stops it at the next line. A failure
    armed through ``POST /api/demo/state`` replaces one step's output and outcome. A clean-up step
    (``always``) plays after a failure or a cancel too, as the real runner runs it; a cancel only
    hurries it along."""

    def __init__(
        self,
        name: str,
        emit: Callable[[core.RunnerEvent], None],
        world: World,
        pace: float,
        backgrounds: Mapping[str, tuple[str, str, bool]] | None = None,
    ) -> None:
        self.name = name
        self.emit = emit
        self.world = world
        self.pace = pace
        self.backgrounds = dict(backgrounds or {})
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._plan: core.Plan | None = None
        self._thread: threading.Thread | None = None
        self._action = ""
        self._cleaning = False

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._plan is not None and (self._thread is None or self._thread.is_alive())

    @property
    def plan(self) -> core.Plan | None:
        with self._lock:
            return self._plan

    def prepare(self, action_id: str) -> None:
        """Names the action the next plan runs for, so an armed failure can find its run."""
        with self._lock:
            self._action = action_id

    def start(self, plan: core.Plan) -> bool:
        with self._lock:
            if self._plan is not None:
                return False
            self._plan, self._thread = plan, None
            action, self._action = self._action, ""
        self.cancel_event.clear()
        thread = threading.Thread(
            target=self._work, args=(plan, action), daemon=True, name=f"demo-{self.name}"
        )
        try:
            thread.start()
        except RuntimeError:
            with self._lock:
                self._plan = None
            return False
        with self._lock:
            if self._plan is plan:
                self._thread = thread
        return True

    def cancel(self) -> bool:
        with self._lock:
            running = self._plan is not None
            cleaning = self._cleaning
        self.cancel_event.set()
        if running and cleaning:
            self._line("Cancel: the clean-up step finishes first, so nothing is left running", None)
        return running

    def _line(self, text: str, tag: str | None) -> None:
        self.emit(core.Line(self.name, text, tag))

    def _step_output(self, label: str) -> Out:
        """A step's made-up output: the failing kind only while the step fails."""
        if scripted_failure(label, self.world):
            return step_lines(label)
        if label == "check the product answers":
            return [("the product answers on http://127.0.0.1:8080/ready", "ok")]
        if label == "lint":
            return [
                ("ruff check: All checks passed!", None),
                ("ruff format --check: 1214 files already formatted", None),
                ("pnpm turbo run lint", None),
                ("eslint: no problems", "ok"),
                ("prettier --check: All matched files use Prettier code style!", "ok"),
            ]
        return step_lines(label)

    def _work(self, plan: core.Plan, action: str) -> None:
        results: list[core.StepResult] = []
        failed = False
        cancelled = False  # a cancel stopped a step or kept one from running
        unclean = False  # a clean-up step failed
        with self.world.lock:
            pace = self.pace / self.world.speed
        self.emit(core.Begin(self.name, plan))
        try:
            for index, step in enumerate(plan.steps):
                if (self.cancel_event.is_set() or failed) and not step.always:
                    state: core.StepState = "cancelled" if self.cancel_event.is_set() else "skipped"
                    cancelled = cancelled or state == "cancelled"
                    results.append(core.StepResult(step.label, state, 0.0))
                    self.emit(core.StepUpdate(self.name, plan, index, step.label, state, 0.0))
                    continue
                with self._lock:
                    self._cleaning = step.always
                self._line(f"\n▸ {step.label}", "step")
                self.emit(core.StepUpdate(self.name, plan, index, step.label, "running", 0.0))
                started = time.monotonic()
                armed = self.world.take_failure(action, index) if action else None
                output: Out = (
                    [(text, "err" if _ERRORISH.search(text) else None) for text in armed.lines]
                    if armed is not None
                    else self._step_output(step.label)
                )
                for text, tag in output:
                    # a cancel stops a step at its next line; a clean-up step still plays out
                    if self.cancel_event.wait(pace) and not step.always:
                        break
                    self._line(text, tag)
                with self._lock:
                    self._cleaning = False
                seconds = time.monotonic() - started
                if self.cancel_event.is_set() and not step.always:
                    state = "cancelled"
                    cancelled = True
                elif armed is not None and armed.state == "timeout":
                    state = "timeout"
                    failed = True
                    limit = step.timeout or seconds
                    self._line(
                        f"error: {step.label} overran its {core.format_seconds(limit)}: SIGTERM "
                        "to its process group, SIGKILL "
                        f"{core.format_seconds(core.KILL_GRACE_SECONDS)} later if it is still "
                        "running",
                        "err",
                    )
                elif armed is not None or scripted_failure(step.label, self.world):
                    state = "failed"
                    failed = True
                    self._line(f"✗ {step.label} failed after {core.format_seconds(seconds)}", "err")
                else:
                    state = "ok"
                unclean = unclean or (step.always and state in ("failed", "timeout"))
                results.append(core.StepResult(step.label, state, seconds))
                self.emit(core.StepUpdate(self.name, plan, index, step.label, state, seconds))
            cancelled = cancelled and not unclean
            if cancelled:
                self._line(f"■ {plan.title} cancelled", "err")
            elif failed:
                self._line(f"✗ {plan.title} failed", "err")
            else:
                self._line(f"✓ {plan.title} done", "ok")
                self._apply(plan.title)
        finally:
            with self._lock:
                self._plan = None
                self._cleaning = False
            self.emit(
                core.End(self.name, plan, not failed and not cancelled, cancelled, tuple(results))
            )

    def _apply(self, title: str) -> None:
        apply = EFFECTS.get(title)
        background = self.backgrounds.get(title)
        with self.world.lock:
            if apply is not None:
                apply(self.world)
            if background is not None:
                kind, service, start = background
                running = self.world.workers if kind == "worker" else self.world.relays
                if start:
                    running.add(service)
                else:
                    running.discard(service)


_ERRORISH: Final = re.compile(r"\b(error|fail|failed|cannot|fatal|refused)\b", re.I)


# ---- the demo backend --------------------------------------------------------------------------

FLAGS: Final = (
    core.FlagRow(
        "review.two_person",
        "bool",
        "regulatory",
        "true",
        "CW_FLAG_REVIEW_TWO_PERSON",
        None,
        "",
        "Two people approve a high-impact rule.",
        "after the pilot",
        "2027-03-31",
    ),
    core.FlagRow(
        "notification.bulk",
        "bool",
        "growth",
        "false",
        "CW_NOTIFICATION_BULK_ENABLED",
        "true",
        ".env",
        "CA firms send a change card to every affected client.",
        "when bulk sends are generally available",
        "2026-12-31",
    ),
    core.FlagRow(
        "pipeline.crawl",
        "bool",
        "pipeline",
        "false",
        "CW_PIPELINE_CRAWL_ENABLED",
        None,
        "",
        "The pipeline crawls the live regulator sites every minute.",
        "never: an operational switch",
        "",
    ),
    core.FlagRow(
        "applicability.fanout",
        "bool",
        "engine",
        "false",
        "CW_APPLICABILITY_FANOUT_ENABLED",
        None,
        "",
        "A published rule fans out to every business.",
        "after the fan-out pilot",
        "2027-01-15",
    ),
    core.FlagRow(
        "qa.citations_strict",
        "bool",
        "qa",
        "true",
        "CW_FLAG_QA_CITATIONS_STRICT",
        None,
        "",
        "Answers without a verified quote are refused.",
        "never",
        "",
    ),
    core.FlagRow(
        "web.new_dashboard",
        "bool",
        "web",
        "false",
        "NEXT_PUBLIC_FLAG_NEW_DASHBOARD",
        "true",
        "apps/web/.env.local",
        "The redesigned business dashboard.",
        "when the new dashboard ships",
        "2026-11-30",
    ),
)


class DemoBackend:
    """The ``--demo`` core: the same shapes as the real one, from canned data."""

    demo = True

    def __init__(self, pace: float = 0.18) -> None:
        self._project = demo_project()
        self.registry = core.Registry(Path("/nonexistent/demo/var/control-panel"))
        self.manager = core.BackgroundManager(
            REPO, self._project.env, self.registry, self._project.known_targets
        )
        self._plans = core.Plans(self._project, self.manager)
        self.build = "Demo · canned data, nothing real runs"
        self.world = World(backups=_now_dumps())
        self.pace = pace
        self.opened: list[str] = []

    @property
    def project(self) -> core.Project:
        return self._project

    @property
    def plans(self) -> core.Plans:
        return self._plans

    def probe_status(self) -> core.Status:
        world = self.world
        with world.lock:
            docker, infra, obs = world.docker, world.infra and world.docker, world.observability
            services, web, product = world.services, world.web, set(world.product)
            workers, relays = set(world.workers), set(world.relays)
        containers: dict[str, core.Container] = {}
        if infra:
            names = list(core.INFRA) + (
                ["langfuse", "otel-collector", "prometheus", "tempo", "grafana"] if obs else []
            )
            ports = {
                "postgres": (5432,),
                "redis": (6379,),
                "redpanda": (19092, 18081),
                "temporal": (7233,),
                "temporal-ui": (8233,),
            }
            for name in names:
                containers[name] = core.Container(
                    name,
                    "running",
                    "healthy" if name != "temporal-ui" else "",
                    "Up 2 hours (healthy)" if name != "temporal-ui" else "Up 2 hours",
                    0,
                    ports.get(name, ()),
                )
        up = {f"service:{name}": index < services for index, name in enumerate(core.SERVICES)}
        up |= {"web": web} | {f"product.{part}": part in product for part in PRODUCT_PARTS}
        background: dict[str, int | None] = {}
        for spec in self._project.backgrounds()[1:]:
            kind, service = spec.key.split("-", 1)
            running = service in (workers if kind == "worker" else relays)
            background[spec.key] = 52000 + len(background) if running else None
        pids = {
            "app": 8662 if product & {"internal", "public"} else None,
            "worker": 8675 if "worker" in product else None,
            "web": 8701 if "web" in product else None,
        }
        provider = "fake" if "internal" in product else None
        return core.Status(docker, containers, up, background, pids, time.time(), provider)

    def probe_processes(self) -> core.ProcessSnapshot:
        world = self.world
        with world.lock:
            services, web, product = world.services, world.web, set(world.product)
            sessions, workers, relays = world.sessions, set(world.workers), set(world.relays)
            infra = world.infra and world.docker
            observability = infra and world.observability
        procs: dict[int, core.Proc] = {
            DEMO_PID: core.Proc(
                DEMO_PID,
                1,
                DEMO_PID,
                420,
                f"{REPO}/.venv/bin/python tools/control-panel/panel_server.py",
            ),
            6841: core.Proc(
                6841,
                1174,
                6841,
                65000,
                "/Applications/Claude.app/Contents/Helpers/disclaimer -- claude",
            ),
            6842: core.Proc(
                6842, 6841, 6841, 65000, f"/Users/you/.local/bin/claude --add-dir {REPO}"
            ),
        }
        origins = {DEMO_PID: "this panel (the window)"}
        guarded: frozenset[int] = frozenset()
        if sessions == "terminal":  # a person's terminal: its make check may be stopped
            procs |= {
                1801: core.Proc(
                    1801,
                    1,
                    1801,
                    20000,
                    "/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal",
                ),
                1802: core.Proc(1802, 1801, 1802, 20000, "login -pf you"),
                1803: core.Proc(1803, 1802, 1803, 20000, "-zsh"),
            }
        if sessions in ("agent", "terminal"):
            parent = 6842 if sessions == "agent" else 1803
            procs |= {
                61000: core.Proc(61000, parent, 61000, 192, "/usr/bin/make check"),
                61001: core.Proc(61001, 61000, 61000, 191, "/bin/bash -c uv run pytest"),
                61002: core.Proc(61002, 61001, 61000, 190, "uv run pytest -m not integration"),
                61003: core.Proc(
                    61003,
                    61002,
                    61000,
                    190,
                    f"{REPO}/.venv/bin/python -m pytest -m not integration --cov",
                ),
            }
            if sessions == "agent":  # Claude Code runs it: named, never stopped from here
                origins |= dict.fromkeys(AGENT_PIDS, "run by Claude Code")
                guarded = frozenset(AGENT_PIDS)
            else:
                origins |= dict.fromkeys(AGENT_PIDS, "other")
        listeners: list[core.Listener] = []
        if infra:  # Colima forwards the containers' ports through one ssh process
            procs[1590] = core.Proc(
                1590, 1, 1590, 9000, "ssh: /Users/you/.colima/_lima/colima/ssh.sock [mux]"
            )
            ports = self._project.ports
            forwarded = [
                "POSTGRES_PORT",
                "REDIS_PORT",
                "REDPANDA_KAFKA_PORT",
                "REDPANDA_SCHEMA_REGISTRY_PORT",
                "REDPANDA_ADMIN_PORT",
                "TEMPORAL_PORT",
                "TEMPORAL_UI_PORT",
            ]
            if observability:
                forwarded += [
                    "LANGFUSE_PORT",
                    "OTEL_GRPC_PORT",
                    "OTEL_HTTP_PORT",
                    "OTEL_HEALTH_PORT",
                    "PROMETHEUS_PORT",
                    "GRAFANA_PORT",
                ]
            listeners += [core.Listener(1590, "ssh", "127.0.0.1", ports[key]) for key in forwarded]
        for index, (name, pid) in enumerate(SERVICE_PIDS.items()):
            if index < services:
                procs[pid] = core.Proc(
                    pid,
                    1,
                    41200,
                    7200,
                    f"{REPO}/.venv/bin/python -m uvicorn {core.service_package(name)}.main:app",
                )
                origins[pid] = "make web-stack"
                listeners.append(
                    core.Listener(pid, "python3.12", "127.0.0.1", self._project.ports.service(name))
                )
        if web:
            procs[76165] = core.Proc(
                76165, 1, 76165, 7100, "node /opt/homebrew/bin/pnpm --filter web dev"
            )
            procs[76180] = core.Proc(76180, 76165, 76165, 7100, "next-server (v16.3.8)")
            origins[76165] = origins[76180] = "panel web app"
            listeners.append(core.Listener(76180, "node", "127.0.0.1", 3000))
        if product & {"internal", "public"}:
            procs[8662] = core.Proc(
                8662, 1, 8662, 900, f"{REPO}/.venv/bin/python {REPO}/.venv/bin/cw-mvp serve"
            )
            origins[8662] = "make product"
            listeners += [
                core.Listener(8662, "python3.12", "127.0.0.1", port)
                for part, port in (("internal", 8080), ("public", 8000))
                if part in product
            ]
        if "worker" in product:
            procs[8675] = core.Proc(
                8675, 1, 8675, 900, f"{REPO}/.venv/bin/python {REPO}/.venv/bin/cw-mvp worker"
            )
            origins[8675] = "make product"
            listeners.append(core.Listener(8675, "python3.12", "127.0.0.1", 8081))
        if "web" in product:
            procs[8701] = core.Proc(
                8701, 1, 8701, 880, "node /opt/homebrew/bin/pnpm dev --port 3400"
            )
            origins[8701] = "make product"
            listeners.append(core.Listener(8701, "node", "127.0.0.1", 3400))
        for index, spec in enumerate(self._project.backgrounds()[1:]):
            kind, service = spec.key.split("-", 1)
            if service in (workers if kind == "worker" else relays):
                pid = 52000 + index
                procs[pid] = core.Proc(pid, 1, pid, 300, " ".join(spec.argv))
                origins[pid] = "this panel"
        outside = {6841, 6842, 1590, 1801, 1802, 1803}
        project = frozenset(pid for pid in procs if pid not in outside | guarded)
        return core.ProcessSnapshot(
            procs, {}, project, origins, tuple(listeners), DEMO_PID, time.time(), "", guarded
        )

    def probe_git(self) -> core.GitState:
        with self.world.lock:
            branch, dirty = self.world.branch, self.world.dirty
        if branch == "main":
            subject = "feat: rule candidate intake and drafting for review (#76)"
            return core.GitState("main", "08b209f", dirty, 0, 0, subject, "2 hours ago")
        subject = "feat: a demo branch for the control app"
        return core.GitState(branch, "4f2c1ab", dirty, 2, 0, subject, "12 minutes ago")

    def probe_kafka(self) -> core.KafkaSnapshot:
        with self.world.lock:
            up = self.world.infra
        if not up:
            return core.KafkaSnapshot(error="Redpanda is not running", taken_at=time.time())
        groups = (
            core.GroupLag(
                "obligation.applicability", "Stable", 1, 0, (("applicability.decided", 0),)
            ),
            core.GroupLag("notification.changes", "Stable", 1, 3, (("rule.published", 3),)),
            core.GroupLag("applicability.profiles", "Empty", 0, 12, (("profile.updated", 12),)),
        )
        topics = (
            core.TopicInfo("applicability.decided", 3, 1204),
            core.TopicInfo("rule.published", 1, 37),
            core.TopicInfo("profile.updated", 3, 311),
            core.TopicInfo("notification.dlq", 1, 2),
        )
        return core.KafkaSnapshot(groups, topics, "", time.time())

    def flags(self) -> tuple[list[core.FlagRow], str]:
        return list(FLAGS), ""

    def backups(self) -> list[core.Dump]:
        with self.world.lock:
            return list(self.world.backups)

    def compose_services(self) -> list[str]:
        return [service.name for service in core.COMPOSE_SERVICES]

    def env_file_exists(self) -> bool:
        return True

    def features(self, status: core.Status | None, last_check: Any) -> list[dict[str, Any]]:
        with self.world.lock:
            product, infra = "internal" in self.world.product, self.world.infra
        web = "http://127.0.0.1:3400"

        def feature(
            id: str,
            title: str,
            summary: str,
            numbers: list[dict[str, Any]],
            links: list[dict[str, Any]],
            source: str,
            needs_product: bool = True,
        ) -> dict[str, Any]:
            live = product if needs_product else infra
            return {
                "id": id,
                "title": title,
                "summary": summary,
                "state": "live" if live else "not-running",
                "numbers": numbers if live else [],
                "links": links,
                "note": ""
                if live
                else (
                    "Start the product to see live numbers."
                    if needs_product
                    else "Start the databases to read it."
                ),
                "source": source,
            }

        def link(label: str, route: str, live: bool = True) -> dict[str, Any]:
            return {"label": label, "url": web + route, "live": live}

        check = last_check or {}
        return [
            feature(
                "review-queue",
                "Review queue",
                "Draft rules waiting for a person to check them.",
                [
                    {"label": "Waiting", "value": 12, "hint": "drafts in the queue"},
                    {"label": "Being reviewed", "value": 2, "hint": "claimed"},
                    {"label": "Decided", "value": 148, "hint": "all time"},
                    {"label": "Oldest waiting", "value": "2d 4h", "hint": "time waiting"},
                ],
                [link("Review queue", "/admin/review", False)],
                "GET /v1/rulebook/review/stats",
            ),
            feature(
                "pipeline-tasks",
                "Pipeline tasks",
                "Documents the pipeline could not handle on its own, by kind.",
                [
                    {"label": "Open tasks", "value": 7, "hint": "first 200"},
                    {"label": "triage", "value": 4, "hint": "open"},
                    {"label": "manual_parse", "value": 3, "hint": "open"},
                ],
                [link("Pipeline tasks", "/admin/pipeline/tasks", False)],
                "GET /v1/pipeline/tasks",
            ),
            feature(
                "fan-out",
                "Fan-out",
                "Published rules being applied to every business, and whether that is on hold.",
                [
                    {"label": "Hold", "value": "off", "hint": "fan-outs run"},
                    {"label": "Runs", "value": 9, "hint": "the last 50"},
                    {"label": "completed", "value": 8, "hint": "runs"},
                    {"label": "running", "value": 1, "hint": "runs"},
                ],
                [link("Fan-outs", "/admin/fan-outs")],
                "GET /v1/applicability-engine/fan-outs",
            ),
            {
                "id": "runs",
                "title": "Eval runs",
                "summary": "Stored runs of the evaluation harness and whether their gates passed.",
                "state": "not-built",
                "numbers": [],
                "links": [],
                "note": "Not built yet: no service serves this route.",
                "source": "GET /v1/eval/runs",
            },
            feature(
                "changes",
                "Rule changes",
                "Published changes to the rulebook.",
                [{"label": "Published changes", "value": "37", "hint": "newest 100"}],
                [link("Impact explorer", "/admin/impact")],
                "GET /v1/changes",
            ),
            feature(
                "obligations",
                "Obligations",
                "What the sample business has to do, and by when.",
                [
                    {"label": "Obligations", "value": 23, "hint": "the sample business"},
                    {"label": "open", "value": 17, "hint": ""},
                    {"label": "completed", "value": 6, "hint": ""},
                ],
                [],
                "GET /v1/obligation/obligations",
            ),
            feature(
                "notifications",
                "Notifications sent",
                "Messages the product sent through its local sink instead of email or WhatsApp.",
                [
                    {"label": "Sent", "value": 54, "hint": "through the sink"},
                    {"label": "Last one", "value": "6m 12s ago", "hint": ""},
                ],
                [link("Notifications", "/admin/notifications")],
                "var/notification/sink.jsonl",
            ),
            feature(
                "dead-outbox",
                "Stuck events (dead outbox)",
                "Events a service saved but could not publish after every retry.",
                [
                    {"label": "Total", "value": 2, "hint": "dead events"},
                    {"label": "notification", "value": 2, "hint": "dead events"},
                ],
                [],
                "outbox_event rows with status dead",
                needs_product=False,
            ),
            {
                "id": "flags",
                "title": "Feature flags",
                "summary": "Switches that turn features on or off, from the flag registry "
                "and .env.",
                "state": "live",
                "numbers": [
                    {"label": "Flags", "value": len(FLAGS), "hint": "in the registry"},
                    {"label": "Changed here", "value": 2, "hint": "set in .env"},
                ],
                "links": [link("Feature flags", "/admin/flags")],
                "note": "",
                "source": "packages/flags/registry.json",
            },
            {
                "id": "product-check",
                "title": "Last product check",
                "summary": "The last time this app checked the product works, step by step.",
                "state": "live" if check else "not-running",
                "numbers": [{"label": "Result", "value": check.get("state", ""), "hint": ""}]
                if check
                else [],
                "links": [],
                "note": ""
                if check
                else "Not run since this app opened. Check the product works runs it.",
                "source": "this app's runs",
            },
            {
                "id": "eval-report",
                "title": "Last eval report",
                "summary": "The newest report the eval harness wrote.",
                "state": "live",
                "numbers": [
                    {"label": "Report", "value": "ci-20261006-0912.json", "hint": "3h 2m ago"},
                    {"label": "Reports", "value": 14, "hint": "in evals/reports"},
                ],
                "links": [],
                "note": "",
                "source": "evals/reports",
            },
        ]

    def github(self, git: core.GitState | None) -> dict[str, Any]:
        base = "https://github.com/example/compliancewatch"
        return {
            "available": True,
            "reason": "",
            "repo_url": base,
            "branch": "demo-branch",
            "links": [
                {"label": label, "url": url}
                for label, url in core.github_links(base, "demo-branch")
            ],
            "prs": [
                {
                    "number": 77,
                    "title": "fix: the control panel no longer freezes after a stop",
                    "url": f"{base}/pull/77",
                    "branch": "control-panel-freeze",
                    "checks": "passing",
                },
                {
                    "number": 76,
                    "title": "feat: list and replay dead letters with make replay",
                    "url": f"{base}/pull/76",
                    "branch": "pipeline-ops",
                    "checks": "pending",
                },
                {
                    "number": 74,
                    "title": "test: a corrected draft takes the reopened extension",
                    "url": f"{base}/pull/74",
                    "branch": "rulebook-extension",
                    "checks": "failing",
                },
            ],
        }

    def log_sources(self) -> list[dict[str, Any]]:
        sources = [
            {
                "id": "web",
                "label": "Web app",
                "group": "Services",
                "path": "var/web-stack/web.log",
                "kind": "file",
                "available": True,
            }
        ]
        sources += [
            {
                "id": f"service:{name}",
                "label": f"{name} service",
                "group": "Services",
                "path": f"var/web-stack/{name}.log",
                "kind": "file",
                "available": True,
            }
            for name in core.SERVICES
        ]
        sources += [
            {
                "id": f"product:{proc}",
                "label": f"Product {proc}",
                "group": "Product",
                "path": f"var/product/{proc}.log",
                "kind": "file",
                "available": True,
            }
            for proc in ("app", "worker", "web")
        ]
        sources += [
            {
                "id": f"container:{s.name}",
                "label": s.what,
                "group": "Containers",
                "path": "",
                "kind": "container",
                "available": True,
            }
            for s in core.COMPOSE_SERVICES[:5]
        ]
        return sources

    def read_log(self, source: str, tail: int) -> dict[str, Any]:
        item = next(s for s in self.log_sources() if s["id"] == source)
        lines = list(_log_lines(source))[-tail:]
        return {
            "id": source,
            "label": item["label"],
            "path": item["path"],
            "taken_at": time.time(),
            "lines": lines,
            "truncated": False,
            "error": "",
        }

    def docs(self) -> list[dict[str, Any]]:
        return [
            {
                "id": key,
                "label": label,
                "path": path,
                "kind": kind,
                "action": "open-doc",
                "params": {"doc": key},
            }
            for key, label, path, kind in catalog.DOCS
        ]

    def open_path(self, path: Path, text_editor: bool) -> None:
        self.opened.append(str(path))

    def open_psql(self) -> str:
        self.opened.append("psql")
        return "Terminal (demo: nothing opened)"

    def make_runner(self, name: str, emit: Callable[[core.RunnerEvent], None]) -> DemoRunner:
        backgrounds: dict[str, tuple[str, str, bool]] = {}
        for spec in self._project.backgrounds()[1:]:
            kind, service = spec.key.split("-", 1)
            for verb in ("start", "stop"):
                backgrounds[f"{verb} the {spec.label}"] = (kind, service, verb == "start")
        return DemoRunner(name, emit, self.world, self.pace, backgrounds)

    # POST /api/demo/state
    def reset_world(self) -> None:
        """The world the UI tests start from: everything stopped, on main, no other session,
        none of the demo's own mishaps, the canned backups."""
        fresh = World(
            docker=False,
            infra=False,
            services=0,
            web=False,
            branch="main",
            sessions="none",
            mishaps=False,
            backups=_now_dumps(),
        )
        with self.world.lock:
            speed = self.world.speed
            for item in fields(World):
                if item.name not in ("lock", "speed"):
                    setattr(self.world, item.name, getattr(fresh, item.name))
            self.world.speed = speed

    def parse_state(self, body: Mapping[str, Any], actions: Collection[str]) -> StateChange:
        """The checked ``world``, ``fail_next`` and ``speed`` of ``POST /api/demo/state``;
        nothing changes until :meth:`apply_state`."""
        fail_next = body.get("fail_next", MISSING)
        return StateChange(
            parse_world(body.get("world", MISSING), self._project),
            parse_failure(fail_next, actions),
            fail_next is not MISSING,
            parse_speed(body.get("speed", MISSING)),
        )

    def apply_state(self, change: StateChange) -> None:
        world = self.world
        with world.lock:
            for name, value in change.world.items():
                if name == "product":
                    for part, on in value.items():
                        (world.product.add if on else world.product.discard)(part)
                elif name in ("workers", "relays"):
                    setattr(world, name, set(value))
                else:
                    setattr(world, name, value)
            if change.set_failure:
                world.failure = change.failure
            if change.speed is not None:
                world.speed = change.speed

    def describe_world(self) -> dict[str, Any]:
        return self.world.describe()


def _log_lines(source: str) -> Iterator[str]:
    """A believable log for each source."""
    if source.startswith("container:"):
        name = source.split(":", 1)[1]
        for minute in range(40):
            yield f"{name}-1  | 2026-10-06 09:{minute:02d}:14 UTC [1] LOG:  checkpoint complete"
        return
    for index in range(120):
        second = index % 60
        if index % 17 == 0:
            yield (
                f"2026-10-06 09:{index // 60:02d}:{second:02d} WARNING slow request: "
                "GET /v1/businesses took 812 ms"
            )
        else:
            status = 200 if index % 9 else 404
            yield (
                f'INFO:     127.0.0.1:{51000 + index} - "GET /health HTTP/1.1" {status} '
                + ("OK" if status == 200 else "Not Found")
            )
