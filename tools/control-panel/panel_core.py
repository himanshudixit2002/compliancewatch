"""The control app's logic, kept apart from its window so it runs and is tested without one.

``panel_server.py`` serves ComplianceWatch Control's window and API; everything it shows or runs
comes from here:

- the checkout it controls (``CW_CONTROL_PANEL_REPO``, else the repo this file sits in) and the
  environment every program gets (a Finder-launched app has a bare PATH);
- the ports, read from ``.env`` with the defaults of ``docker-compose.yml`` and the Makefile;
- parsers for what the probes read: ``docker compose ps``, ``lsof``, ``ps``, ``git``, ``rpk``,
  the flag registry, the web app's screen registry, the Makefile and the product check's steps;
- which processes belong to the checkout, which of them this panel started, and what a stop may
  signal (never the panel, never a process outside the checkout);
- the command plan behind every button, and the checks that keep the forbidden targets out of
  every plan;
- the runner that streams a plan's output, stops a step that overruns its time and cancels its
  process group;
- one probe of each kind at a time, and hard timeouts on every program it reads from.

Every program runs as an argument list, never through a shell.
"""

from __future__ import annotations

import codecs
import contextlib
import http.client
import json
import os
import re
import select
import shlex
import signal
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, Protocol

# ---- the checkout and the environment ---------------------------------------------------------

REPO_ENV: Final = "CW_CONTROL_PANEL_REPO"


def repo_root(environ: Mapping[str, str] | None = None) -> Path:
    """The checkout the panel controls: ``CW_CONTROL_PANEL_REPO``, else the repo of this file."""
    environ = os.environ if environ is None else environ
    override = environ.get(REPO_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


DROPPED_VARIABLES: Final = (
    # make reads its variables from the environment: ARGS=--destructive exported where the panel
    # was opened, or given to `make control-panel` (it then travels in MAKEFLAGS), would reach
    # make product-check
    "ARGS",
    "MAKEFLAGS",
    "MFLAGS",
    "GNUMAKEFLAGS",
    "MAKELEVEL",
    "MAKEOVERRIDES",
    # and the variables the panel's own plans pass when they mean to
    "SERVICE",
    "PROC",
    "FOLLOW",
    "FILE",
    "WEB",
)
"""Never passed on to a program the panel runs."""


def program_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment of every program the panel runs.

    A Finder-launched app gets a bare PATH, so Homebrew's tools go first and uv's installer
    directory last. Python output is unbuffered so a step's lines stream as they are printed.
    None of :data:`DROPPED_VARIABLES` is passed on, and the crawl is off for everything the panel
    starts, whatever .env says: a crawl reads the live regulator sites.
    """
    source = os.environ if environ is None else environ
    env = {key: value for key, value in source.items() if key not in DROPPED_VARIABLES}
    home = env.get("HOME") or str(Path.home())
    current = env.get("PATH") or "/usr/bin:/bin:/usr/sbin:/sbin"
    parts: list[str] = []
    for part in ["/opt/homebrew/bin", "/usr/local/bin", *current.split(":"), f"{home}/.local/bin"]:
        if part and part not in parts:
            parts.append(part)
    env["PATH"] = ":".join(parts)
    env["PYTHONUNBUFFERED"] = "1"
    env["CW_PIPELINE_CRAWL_ENABLED"] = "false"
    env.pop(REPO_ENV, None)
    return env


# ---- inventory ---------------------------------------------------------------------------------

SERVICES: Final = (
    "identity",
    "profile",
    "rulebook",
    "applicability-engine",
    "obligation",
    "notification",
    "qa",
    "llm-gateway",
    "eval",
    "pipeline",
)
"""The Makefile's SERVICES, in its order: make web-stack puts them on SERVICE_PORT_BASE+1..10."""

_PACKAGES: Final = {"profile": "profile_service", "eval": "eval_service"}
INFRA: Final = ("postgres", "redis", "redpanda", "temporal", "temporal-ui")
COMPOSE_PROFILES: Final = ("observability", "llm", "flags", "mvp")


def service_package(service: str) -> str:
    """The import package of a service directory (two avoid shadowing the standard library)."""
    return _PACKAGES.get(service, service.replace("-", "_"))


@dataclass(frozen=True)
class ComposeService:
    name: str
    profile: str
    what: str


COMPOSE_SERVICES: Final = (
    ComposeService("postgres", "", "Postgres 16 + pgvector"),
    ComposeService("redis", "", "Redis 7"),
    ComposeService("redpanda", "", "Kafka API (Redpanda)"),
    ComposeService("temporal", "", "Temporal"),
    ComposeService("temporal-ui", "", "Temporal UI"),
    ComposeService("langfuse", "observability", "Langfuse"),
    ComposeService("otel-collector", "observability", "OpenTelemetry collector"),
    ComposeService("prometheus", "observability", "Prometheus"),
    ComposeService("tempo", "observability", "Tempo (traces, through Grafana)"),
    ComposeService("grafana", "observability", "Grafana"),
    ComposeService("fake-llm", "llm", "fake LLM gateway"),
    ComposeService("unleash", "flags", "Unleash"),
    ComposeService("mvp-release", "mvp", "image product: release step"),
    ComposeService("mvp-app", "mvp", "image product: app"),
    ComposeService("mvp-worker", "mvp", "image product: worker"),
)


def compose(*args: str) -> tuple[str, ...]:
    """``docker compose`` with every profile named, as make dev-ps and make dev-down name them."""
    profiles = [part for profile in COMPOSE_PROFILES for part in ("--profile", profile)]
    return ("docker", "compose", *profiles, *args)


RPK: Final = ("docker", "compose", "exec", "-T", "redpanda", "rpk")
# The Colima VM docs/onboarding/local-dev.md asks for: 4 CPUs, 8 GB of memory, 60 GB of disk.
COLIMA_START: Final = (
    *("colima", "start", "--cpu", "4", "--memory", "8", "--disk", "60"),
    *("--dns", "1.1.1.1", "--dns", "8.8.8.8"),
)

# ---- ports -------------------------------------------------------------------------------------

PORT_DEFAULTS: Final[Mapping[str, int]] = {
    "POSTGRES_PORT": 5432,
    "REDIS_PORT": 6379,
    "REDPANDA_KAFKA_PORT": 19092,
    "REDPANDA_SCHEMA_REGISTRY_PORT": 18081,
    "REDPANDA_ADMIN_PORT": 19644,
    "TEMPORAL_PORT": 7233,
    "TEMPORAL_UI_PORT": 8233,
    "LANGFUSE_PORT": 3010,
    "OTEL_GRPC_PORT": 4317,
    "OTEL_HTTP_PORT": 4318,
    "OTEL_HEALTH_PORT": 13133,
    "PROMETHEUS_PORT": 9090,
    "GRAFANA_PORT": 3030,
    "FAKE_LLM_PORT": 8090,
    "UNLEASH_PORT": 4242,
    "SERVICE_PORT_BASE": 8000,
    "WEB_PORT": 3000,
    "CW_MVP_PUBLIC_PORT": 8000,
    "CW_MVP_INTERNAL_PORT": 8080,
    "PRODUCT_WORKER_PORT": 8081,
}
# PRODUCT_WORKER_PORT is a make variable: the environment or the make command line sets it, and
# .env never does (only the recipes' shells source .env).
_MAKE_VARIABLES: Final = frozenset({"PRODUCT_WORKER_PORT"})

PRODUCT_WEB_PORT: Final = 3400
"""The panel runs make product with WEB_PORT=3400, beside the UI-only web app on 3000, and opens
it at 127.0.0.1 so the two sessions keep their own cookies (docs/onboarding/product.md)."""
PRODUCT_E2E_PORT: Final = 3401
"""make product-e2e's next start: 3400 is the product's own web app when the panel started it."""


@dataclass(frozen=True)
class Ports:
    values: Mapping[str, int]

    def __getitem__(self, key: str) -> int:
        return self.values.get(key, PORT_DEFAULTS[key])

    def service(self, name: str) -> int:
        return self["SERVICE_PORT_BASE"] + SERVICES.index(name) + 1


def resolve_ports(env_file: Mapping[str, str], environ: Mapping[str, str]) -> Ports:
    """Every port, as the Makefile's recipes see it: the environment wins over .env."""
    values: dict[str, int] = {}
    for key, default in PORT_DEFAULTS.items():
        raw = environ.get(key) or ("" if key in _MAKE_VARIABLES else env_file.get(key, ""))
        raw = raw.strip()
        values[key] = int(raw) if raw.isdigit() and 0 < int(raw) < 65536 else default
    return Ports(values)


@dataclass(frozen=True)
class PortInfo:
    port: int
    what: str
    group: str
    url: str | None = None


def port_catalogue(ports: Ports) -> list[PortInfo]:
    """Every port the project listens on, both stacks, the infrastructure and the tools."""
    web = ports["WEB_PORT"]
    entries = [
        PortInfo(ports["POSTGRES_PORT"], "Postgres", "infra"),
        PortInfo(ports["REDIS_PORT"], "Redis", "infra"),
        PortInfo(ports["REDPANDA_KAFKA_PORT"], "Kafka API (Redpanda)", "infra"),
        PortInfo(ports["REDPANDA_SCHEMA_REGISTRY_PORT"], "Redpanda schema registry", "infra"),
        PortInfo(ports["REDPANDA_ADMIN_PORT"], "Redpanda admin API", "infra"),
        PortInfo(ports["TEMPORAL_PORT"], "Temporal", "infra"),
        PortInfo(
            ports["TEMPORAL_UI_PORT"],
            "Temporal UI",
            "infra",
            f"http://localhost:{ports['TEMPORAL_UI_PORT']}",
        ),
        PortInfo(ports["LANGFUSE_PORT"], "Langfuse", "observability"),
        PortInfo(ports["OTEL_GRPC_PORT"], "OTel collector gRPC", "observability"),
        PortInfo(ports["OTEL_HTTP_PORT"], "OTel collector HTTP", "observability"),
        PortInfo(ports["OTEL_HEALTH_PORT"], "OTel collector health", "observability"),
        PortInfo(ports["PROMETHEUS_PORT"], "Prometheus", "observability"),
        PortInfo(ports["GRAFANA_PORT"], "Grafana", "observability"),
        PortInfo(ports["FAKE_LLM_PORT"], "fake LLM gateway", "llm"),
        PortInfo(ports["UNLEASH_PORT"], "Unleash", "flags"),
    ]
    entries += [
        PortInfo(
            ports.service(name), name, "UI-only stack", f"http://localhost:{ports.service(name)}"
        )
        for name in SERVICES
    ]
    entries += [
        PortInfo(web, "web app (next dev)", "UI-only stack", f"http://localhost:{web}"),
        PortInfo(ports["CW_MVP_PUBLIC_PORT"], "product public listener", "product"),
        PortInfo(ports["CW_MVP_INTERNAL_PORT"], "product internal listener", "product"),
        PortInfo(ports["PRODUCT_WORKER_PORT"], "product worker health", "product"),
        PortInfo(PRODUCT_WEB_PORT, "product web app", "product"),
    ]
    return sorted(entries, key=lambda entry: entry.port)


def stack_links(ports: Ports) -> list[tuple[str, str, str]]:
    """The UIs and endpoints the compose stack serves, as (label, URL, container). Redpanda has no
    console in this stack, so its admin API and schema registry stand for it."""
    return [
        ("Temporal UI", f"http://localhost:{ports['TEMPORAL_UI_PORT']}", "temporal-ui"),
        ("Grafana", f"http://localhost:{ports['GRAFANA_PORT']}", "grafana"),
        ("Prometheus", f"http://localhost:{ports['PROMETHEUS_PORT']}", "prometheus"),
        ("Langfuse", f"http://localhost:{ports['LANGFUSE_PORT']}", "langfuse"),
        ("Unleash", f"http://localhost:{ports['UNLEASH_PORT']}", "unleash"),
        (
            "Redpanda admin API",
            f"http://localhost:{ports['REDPANDA_ADMIN_PORT']}/v1/cluster/health_overview",
            "redpanda",
        ),
        (
            "Schema registry",
            f"http://localhost:{ports['REDPANDA_SCHEMA_REGISTRY_PORT']}/subjects",
            "redpanda",
        ),
        (
            "OTel collector health",
            f"http://localhost:{ports['OTEL_HEALTH_PORT']}/",
            "otel-collector",
        ),
        ("Fake LLM gateway docs", f"http://localhost:{ports['FAKE_LLM_PORT']}/docs", "fake-llm"),
    ]


# ---- parsers -----------------------------------------------------------------------------------

_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def parse_env_file(text: str) -> dict[str, str]:
    """KEY=VALUE lines as a shell's ``set -a; . ./.env`` reads the simple ones."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not _ENV_KEY.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values


def read_env_file(path: Path) -> dict[str, str]:
    try:
        return parse_env_file(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}


_TARGET = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_-]*)\s*:(?![=:])(?:[^#]*?##\s*(.*))?")
_CHECKS = re.compile(r"^CHECKS\s*(:=|\+=|=)\s*(.*)$")


def parse_make_targets(text: str) -> dict[str, str]:
    """Each target of a Makefile with its ``##`` help text (empty when it has none)."""
    targets: dict[str, str] = {}
    for line in text.splitlines():
        match = _TARGET.match(line)
        if match:
            targets.setdefault(match.group(1), (match.group(2) or "").strip())
    return targets


def parse_checks(text: str) -> list[str]:
    """The gates make check runs: the CHECKS list with every ``CHECKS +=`` line after it."""
    gates: list[str] = []
    for line in text.splitlines():
        match = _CHECKS.match(line)
        if not match:
            continue
        names = match.group(2).split("#", 1)[0].split()
        if match.group(1) != "+=":
            gates = []
        gates += [name for name in names if name not in gates]
    return gates


_STEP = re.compile(r'\bStep\(\s*"([a-z][a-z0-9_-]*)"')
CHECK_STEPS_FALLBACK: Final = (
    *("health", "honesty", "loop", "isolation", "recompute", "fanout", "reminders"),
    *("rollback", "tracking", "changes", "public", "sources", "review"),
)
NEVER_STEPS: Final = frozenset({"rollback"})
"""rollback withdraws gstr9_annual and runs only with --destructive, which the panel never passes:
the shared dev database keeps gstr9_annual published (docs/onboarding/product.md, Honesty)."""


def parse_check_steps(text: str) -> list[str]:
    """The step names of cw-product check, in order (tools/demo/src/cw_demo/product/check.py)."""
    steps: list[str] = []
    for name in _STEP.findall(text):
        if name not in steps:
            steps.append(name)
    return steps


def selectable_steps(steps: Iterable[str]) -> list[str]:
    return [step for step in steps if step not in NEVER_STEPS]


@dataclass(frozen=True)
class Container:
    service: str
    state: str
    health: str
    status: str
    exit_code: int
    ports: tuple[int, ...]

    @property
    def up(self) -> bool:
        return self.state == "running" and self.health in ("", "healthy")


def parse_compose_ps(text: str) -> dict[str, Container]:
    """``docker compose ps --format json``: one object per line (compose 2.21+) or one array."""
    rows: list[Any] = []
    text = text.strip()
    if text.startswith("["):
        with contextlib.suppress(ValueError):
            loaded = json.loads(text)
            rows = loaded if isinstance(loaded, list) else []
    else:
        for line in text.splitlines():
            with contextlib.suppress(ValueError):
                rows.append(json.loads(line))
    containers: dict[str, Container] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("Service"):
            continue
        published: list[int] = []
        for publisher in row.get("Publishers") or []:
            port = publisher.get("PublishedPort") if isinstance(publisher, dict) else None
            if isinstance(port, int) and port > 0 and port not in published:
                published.append(port)
        exit_code = row.get("ExitCode")
        containers[str(row["Service"])] = Container(
            service=str(row["Service"]),
            state=str(row.get("State") or ""),
            health=str(row.get("Health") or ""),
            status=str(row.get("Status") or ""),
            exit_code=exit_code if isinstance(exit_code, int) else 0,
            ports=tuple(sorted(published)),
        )
    return containers


@dataclass(frozen=True)
class Listener:
    pid: int
    command: str
    address: str
    port: int


def parse_lsof_listen(text: str) -> list[Listener]:
    """``lsof -nP -iTCP -sTCP:LISTEN -F pcn``: the listening sockets, one per pid and port."""
    listeners: list[Listener] = []
    seen: set[tuple[int, int]] = set()
    pid, command = 0, ""
    for line in text.splitlines():
        if not line:
            continue
        tag, value = line[0], line[1:]
        if tag == "p":
            pid = int(value) if value.isdigit() else 0
            command = ""
        elif tag == "c":
            command = value
        elif tag == "n" and pid:
            address, _, port = value.rpartition(":")
            if port.isdigit() and (pid, int(port)) not in seen:
                seen.add((pid, int(port)))
                listeners.append(Listener(pid, command, address, int(port)))
    return listeners


def parse_lsof_cwd(text: str) -> dict[int, tuple[str, str]]:
    """``lsof -a -d cwd -F pcn``: each process's name and working directory."""
    found: dict[int, tuple[str, str]] = {}
    pid, name = 0, ""
    for line in text.splitlines():
        if not line:
            continue
        tag, value = line[0], line[1:]
        if tag == "p":
            pid = int(value) if value.isdigit() else 0
            name = ""
        elif tag == "c":
            name = value
        elif tag == "n" and pid:
            found[pid] = (name, value)
    return found


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    pgid: int
    elapsed: int
    command: str


PS_ARGV: Final = ("/bin/ps", "-axww", "-o", "pid=,ppid=,pgid=,etime=,command=")


def parse_etime(text: str) -> int:
    """ps's ``[[dd-]hh:]mm:ss`` as seconds."""
    days = 0
    text = text.strip()
    if "-" in text:
        head, text = text.split("-", 1)
        days = int(head) if head.isdigit() else 0
    try:
        parts = [int(part) for part in text.split(":")]
    except ValueError:
        return 0
    while len(parts) < 3:
        parts.insert(0, 0)
    hours, minutes, seconds = parts[-3:]
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def parse_ps(text: str) -> dict[int, Proc]:
    procs: dict[int, Proc] = {}
    for line in text.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4 or not all(part.isdigit() for part in parts[:3]):
            continue
        pid, ppid, pgid = (int(part) for part in parts[:3])
        command = parts[4] if len(parts) == 5 else ""
        procs[pid] = Proc(pid, ppid, pgid, parse_etime(parts[3]), command.strip())
    return procs


def format_seconds(seconds: float) -> str:
    total = int(seconds)
    if total < 60:
        return f"{total} s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours:02d}h"


@dataclass(frozen=True)
class GitState:
    branch: str = ""
    sha: str = ""
    dirty: int = 0
    ahead: int | None = None
    behind: int | None = None
    subject: str = ""
    when: str = ""
    error: str = ""

    @property
    def on_main(self) -> bool:
        return self.branch == "main"


def count_porcelain(text: str) -> int:
    """Uncommitted paths in ``git status --porcelain=v1`` (untracked ones included)."""
    return sum(1 for line in text.splitlines() if line.strip() and not line.startswith("##"))


def parse_ahead_behind(text: str) -> tuple[int, int] | None:
    """``git rev-list --left-right --count origin/main...HEAD``: (ahead, behind) of HEAD."""
    parts = text.split()
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    behind, ahead = int(parts[0]), int(parts[1])
    return ahead, behind


_GITHUB = re.compile(
    r"^(?:https?://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


def github_url(remote: str) -> str | None:
    """The repository's page for a GitHub remote; credentials in the URL are never kept."""
    match = _GITHUB.match(remote.strip())
    return f"https://github.com/{match.group(1)}/{match.group(2)}" if match else None


def github_links(base: str, branch: str) -> list[tuple[str, str]]:
    links = [
        ("Pull requests", f"{base}/pulls"),
        ("Actions", f"{base}/actions"),
        ("Repository", base),
    ]
    if branch and branch != "HEAD":
        quoted = urllib.parse.quote(branch, safe="/")
        links.append((f"Branch {branch}", f"{base}/tree/{quoted}"))
        if branch != "main":
            links.append(("Compare with main", f"{base}/compare/main...{quoted}"))
    return links


@dataclass(frozen=True)
class GroupLag:
    group: str
    state: str
    members: int
    total_lag: int
    topics: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class TopicInfo:
    name: str
    partitions: int
    messages: int | None

    @property
    def dead_letters(self) -> bool:
        return self.name.endswith(".dlq")


def _as_int(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _json_list(text: str) -> list[Any]:
    text = text.strip()
    if not text:
        return []
    loaded = json.loads(text)
    if isinstance(loaded, dict):
        return [loaded]
    return loaded if isinstance(loaded, list) else []


def parse_rpk_groups(text: str) -> list[GroupLag]:
    """``rpk group describe --format json``: each consumer group with its lag per topic."""
    groups: list[GroupLag] = []
    for row in _json_list(text):
        if not isinstance(row, dict) or not row.get("group_name"):
            continue
        lag: dict[str, int] = {}
        for partition in row.get("partitions") or []:
            if isinstance(partition, dict) and partition.get("topic"):
                topic = str(partition["topic"])
                lag[topic] = lag.get(topic, 0) + max(_as_int(partition.get("lag")), 0)
        groups.append(
            GroupLag(
                group=str(row["group_name"]),
                state=str(row.get("state") or ""),
                members=_as_int(row.get("members")),
                total_lag=_as_int(row.get("total_lag"), sum(lag.values())),
                topics=tuple(sorted(lag.items())),
            )
        )
    return sorted(groups, key=lambda group: group.group)


def parse_rpk_topics(text: str) -> list[TopicInfo]:
    """``rpk topic describe -p --format json`` (or ``rpk topic list --format json``)."""
    topics: list[TopicInfo] = []
    for row in _json_list(text):
        if not isinstance(row, dict):
            continue
        nested = row.get("summary")
        summary: dict[str, Any] = nested if isinstance(nested, dict) else row
        name = str(summary.get("name") or "")
        if not name or summary.get("internal") is True or name.startswith("_"):
            continue
        partitions = row.get("partitions")
        messages: int | None = None
        if isinstance(partitions, list):
            messages = sum(
                max(_as_int(p.get("high_watermark")) - _as_int(p.get("log_start_offset")), 0)
                for p in partitions
                if isinstance(p, dict)
            )
            count = _as_int(summary.get("partitions"), len(partitions))
        else:
            count = _as_int(partitions)
        topics.append(TopicInfo(name, count, messages))
    return sorted(topics, key=lambda topic: topic.name)


@dataclass(frozen=True)
class FlagRow:
    name: str
    type: str
    owner: str
    default: str
    env: str
    value: str | None
    source: str
    description: str
    removal: str
    expires: str


def flag_variable(entry: Mapping[str, Any]) -> str:
    """The variable that sets a flag: its own ``env``, else ``CW_FLAG_<NAME>`` (py_common.flags)."""
    env = entry.get("env")
    if isinstance(env, str) and env:
        return env
    return "CW_FLAG_" + str(entry.get("name", "")).upper().replace(".", "_")


def _display(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def flag_rows(
    registry_text: str, env_files: Sequence[tuple[str, Mapping[str, str]]]
) -> list[FlagRow]:
    """The flag registry, each flag with the value the first env file that sets it gives."""
    loaded = json.loads(registry_text)
    entries = loaded.get("flags", []) if isinstance(loaded, dict) else []
    rows: list[FlagRow] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        variable = flag_variable(entry)
        value: str | None = None
        source = ""
        for name, values in env_files:
            if variable in values:
                value, source = values[variable], name
                break
        rows.append(
            FlagRow(
                name=str(entry["name"]),
                type=_display(entry.get("type")),
                owner=_display(entry.get("owner")),
                default=_display(entry.get("default")),
                env=variable,
                value=value,
                source=source,
                description=_display(entry.get("description")),
                removal=_display(entry.get("removal")),
                expires=_display(entry.get("expires")),
            )
        )
    return rows


@dataclass(frozen=True)
class ScreenEntry:
    id: str
    route: str
    title: str
    status: str

    @property
    def static(self) -> bool:
        return "[" not in self.route


_SCREEN_ID = re.compile(r'\bid:\s*"([a-z][a-z0-9._-]*)"')


def parse_screens(text: str) -> list[ScreenEntry]:
    """The web app's screen registry (apps/web/src/shared/config/screens.ts): id, route, status."""
    marks = list(_SCREEN_ID.finditer(text))
    screens: list[ScreenEntry] = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        chunk = text[mark.end() : end]
        route = re.search(r'\broute:\s*"([^"]+)"', chunk)
        title = re.search(r'\btitle:\s*"([^"]*)"', chunk)
        status = re.search(r'\bstatus:\s*"([a-z]+)"', chunk)
        if route and status:
            screens.append(
                ScreenEntry(
                    mark.group(1), route.group(1), title.group(1) if title else "", status.group(1)
                )
            )
    return screens


SCREENS_FALLBACK: Final = (
    ScreenEntry("admin.home", "/admin", "Internal tools", "live"),
    ScreenEntry("admin.fan-outs", "/admin/fan-outs", "Fan-outs", "live"),
    ScreenEntry("admin.decisions", "/admin/decisions", "Decision review", "live"),
    ScreenEntry("admin.review", "/admin/review", "Review queue", "ready"),
    ScreenEntry("admin.flags", "/admin/flags", "Feature flags", "live"),
    ScreenEntry("admin.notifications", "/admin/notifications", "Notifications", "live"),
    ScreenEntry("admin.impact", "/admin/impact", "Impact explorer", "live"),
    ScreenEntry("admin.rulebook.versions", "/admin/rulebook/versions", "Rule versions", "live"),
    ScreenEntry("admin.rulebook.documents", "/admin/rulebook/documents", "Documents", "live"),
    ScreenEntry("admin.rulebook.search", "/admin/rulebook/search", "Clause search", "live"),
    ScreenEntry("admin.pipeline", "/admin/pipeline", "Pipeline", "waiting"),
    ScreenEntry("admin.pipeline.tasks", "/admin/pipeline/tasks", "Pipeline tasks", "ready"),
    ScreenEntry("admin.sources", "/admin/sources", "Sources", "ready"),
)
"""origin/main's admin screens, for a checkout whose registry cannot be read."""

PRODUCT_ADMIN: Final = (
    "admin.fan-outs",
    "admin.decisions",
    "admin.review",
    "admin.flags",
    "admin.notifications",
)
PIPELINE_ADMIN: Final = (
    "admin.pipeline",
    "admin.pipeline.tasks",
    "admin.sources",
    "admin.review",
    "admin.review.stats",
)


def admin_pages(
    screens: Sequence[ScreenEntry], first: Sequence[str], only: bool = False
) -> tuple[list[ScreenEntry], list[ScreenEntry]]:
    """The live admin pages without a path parameter (``first`` in its order, then the rest by
    title, or only ``first`` with ``only``), and the pages of ``first`` that are not live yet."""
    by_id = {screen.id: screen for screen in screens}
    live = [s for s in screens if s.id.startswith("admin.") and s.status == "live" and s.static]
    head = [by_id[key] for key in first if key in by_id and by_id[key] in live]
    rest = [] if only else sorted((s for s in live if s not in head), key=lambda s: s.title)
    missing = [by_id[key] for key in first if key in by_id and by_id[key] not in live]
    return head + rest, missing


# ---- processes ---------------------------------------------------------------------------------

DENIED_NAMES: Final = frozenset(
    {
        # Shells, terminals and agents a person runs in the checkout
        "zsh",
        "-zsh",
        "fish",
        "login",
        "tmux",
        "screen",
        "claude",
        "disclaimer",
        # Colima's VM and its port forwarding
        "ssh",
        "limactl",
        "colima",
        "lima",
        # The probes themselves
        "lsof",
        "ps",
        "git",
    }
)
_ROOT_NAMES: Final = frozenset({"make", "gnumake", "uv", "pnpm", "pytest", "alembic"})
_TOOL_NAMES: Final = _ROOT_NAMES | {"docker", "bash", "sh", "tail"}
# Editors' helper processes name the folder they have open; they are not the checkout's
_DENIED_PREFIXES: Final = ("Code Helper", "Cursor Helper", "Electron", "Visual Studio Code")
# Claude Code keeps its worktrees and state in the checkout: what runs there is not the checkout's
_EXCLUDED_DIRS: Final = ("/.claude/",)
_PNPM_SCRIPTS: Final = frozenset({"pnpm", "pnpm.cjs", "pnpm.mjs", "pnpm.js"})
PANEL_MARKERS: Final = ("control-panel/control_panel.py", "control-panel/panel_server.py")
"""A control window's command line holds one of these: ComplianceWatch Control's helper, or the
retired tkinter panel, which an app installed before it was retired still runs; from a checkout
(tools/control-panel) or from ComplianceWatch.app's own copy (Contents/Resources/control-panel)."""


def is_control_panel(command: str) -> bool:
    return any(marker in command for marker in PANEL_MARKERS)


def _under(path: str, repo: str) -> bool:
    """``path`` is the checkout or inside it, and not inside one of :data:`_EXCLUDED_DIRS`."""
    if path != repo and not path.startswith(repo + "/"):
        return False
    return not (path[len(repo) :] + "/").startswith(_EXCLUDED_DIRS)


def _mentions(command: str, repo: str) -> bool:
    """The command line names a path of the checkout, outside :data:`_EXCLUDED_DIRS`."""
    for match in re.finditer(re.escape(repo) + r"(?=[/\s'\"]|$)", command):
        if not command[match.end() :].startswith(_EXCLUDED_DIRS):
            return True
    return False


def _node_script_in(parts: Sequence[str], cwd: str, repo: str) -> bool:
    """``node <script>`` is the checkout's when the script is a file of the checkout, or pnpm
    running in it; a tool named elsewhere on the line (an agent's MCP server) does not count."""
    if not parts or not re.fullmatch(r"node[0-9.]*", Path(parts[0]).name):
        return False
    script = next((part for part in parts[1:] if not part.startswith("-")), "")
    if not script:
        return False
    path = os.path.normpath(script if script.startswith("/") else os.path.join(cwd, script))
    return _under(path, repo) or (Path(script).name in _PNPM_SCRIPTS and _under(cwd, repo))


_TOOL_SERVERS: Final = re.compile(
    r"(?:^|[\s/])(?:ruff\s+server|ruff-lsp|pylsp|pyls|pyright(?:-langserver)?|"
    r"basedpyright(?:-langserver)?|jedi-language-server|dmypy|mypy\.dmypy|tsserver(?:\.js)?|"
    r"typescript-language-server|vtsls|vscode-eslint-language-server|eslintServer(?:\.js)?|"
    r"eslint_d|tailwindcss-language-server|vscode-json-language-server|"
    r"yaml-language-server)(?:\s|$)"
)
"""Language servers and editor helpers: an editor starts them for the folder it has open, and
they are never the checkout's to stop."""


def is_tool_server(command: str) -> bool:
    return _TOOL_SERVERS.search(command) is not None


def is_project_root(name: str, command: str, cwd: str, repo: str) -> bool:
    """A process of the checkout in its own right, not only as the child of one: make, uv run,
    pnpm, the repo's Python or a Node script of the checkout, running in the checkout or naming a
    path in it. Shells, agents and the tools they fetch (uvx, uv tool), editors, their language
    servers and Colima never are, nor is anything in a worktree under .claude/."""
    if name in DENIED_NAMES or name.startswith(_DENIED_PREFIXES):
        return False
    if is_tool_server(command):
        return False
    parts = command.split()
    first = Path(parts[0]).name if parts else ""
    if "uvx" in (name, first) or (first == "uv" and parts[1:2] == ["tool"]):
        return False
    if "node" in (name, first):
        return _node_script_in(parts, cwd, repo)
    under = _under(cwd, repo)
    if _mentions(command, repo) and (under or name.startswith("python") or name in _TOOL_NAMES):
        return True
    if not under:
        return False
    if name in _ROOT_NAMES or first in _ROOT_NAMES:
        return True
    if name.startswith("python"):
        return bool(parts) and parts[0].startswith((".venv/", "./.venv/"))
    if name == "docker":
        return " compose" in command
    return False


def project_pids(
    procs: Mapping[int, Proc], names: Mapping[int, tuple[str, str]], repo: Path
) -> set[int]:
    """The checkout's processes: the roots above, and their children whose working directory is
    in the checkout too (a child lsof saw no directory for has exited, or is not ours to read)."""
    where = str(repo)
    found = {
        pid
        for pid, proc in procs.items()
        if pid in names and is_project_root(names[pid][0], proc.command, names[pid][1], where)
    }
    children: dict[int, list[int]] = defaultdict(list)
    for proc in procs.values():
        children[proc.ppid].append(proc.pid)
    queue = sorted(found)
    while queue:
        for child in children.get(queue.pop(), []):
            if child in found or child not in names:
                continue
            name, cwd = names[child]
            command = procs[child].command if child in procs else ""
            if name in DENIED_NAMES or is_tool_server(command) or not _under(cwd, where):
                continue
            found.add(child)
            queue.append(child)
    return found


def ancestors(pid: int, procs: Mapping[int, Proc]) -> list[int]:
    chain: list[int] = []
    current = procs.get(pid)
    while current is not None and current.ppid > 1 and current.ppid not in chain:
        chain.append(current.ppid)
        current = procs.get(current.ppid)
    return chain


_EDITORS: Final = re.compile(
    r"Visual Studio Code|Code Helper|/Code\.app/|Cursor Helper|/Cursor\.app/|Electron|"
    r"/Zed\.app/|JetBrains|PyCharm|IntelliJ|WebStorm|Sublime Text|(?:^|/)(?:n?vim|emacs)(?:\s|$)"
)
_AGENTS: Final = re.compile(
    r"(^|/)claude(\s|$)|Claude\.app|claude-code|/\.claude/|(^|/)(codex|aider)(\s|$)", re.I
)


def guard_reason(pid: int, procs: Mapping[int, Proc], self_pid: int) -> str:
    """Who runs a process of the checkout when it is not the person's own: ``Claude Code`` (or
    another agent, its shells included, such as ``bash -c "cd <repo> && make check"``) or ``an
    editor`` among its ancestors; ``""`` otherwise, and for what this window started."""
    for parent in ancestors(pid, procs):
        if parent == self_pid:
            return ""
        command = procs[parent].command if parent in procs else ""
        if _AGENTS.search(command):
            return "Claude Code"
        if _EDITORS.search(command):
            return "an editor"
    return ""


def split_guarded(
    found: Collection[int], procs: Mapping[int, Proc], self_pid: int
) -> tuple[set[int], dict[int, str]]:
    """The checkout's processes this app may stop, and those an editor or an agent runs, with
    who runs each (:func:`guard_reason`)."""
    guarded = {pid: who for pid in found if (who := guard_reason(pid, procs, self_pid))}
    return set(found) - guarded.keys(), guarded


def descendants(pid: int, procs: Mapping[int, Proc]) -> list[int]:
    children: dict[int, list[int]] = defaultdict(list)
    for proc in procs.values():
        children[proc.ppid].append(proc.pid)
    found: list[int] = []
    queue = [pid]
    while queue:
        for child in children.get(queue.pop(), []):
            if child not in found and child != pid:
                found.append(child)
                queue.append(child)
    return found


def control_panels(procs: Mapping[int, Proc]) -> set[int]:
    """Every control panel window, this one and any other."""
    return {pid for pid, proc in procs.items() if is_control_panel(proc.command)}


def short_command(command: str, repo: Path, limit: int = 90) -> str:
    """A command line without the checkout's path or the venv's interpreter in front (``python
    -m pytest -q`` reads ``pytest -q``)."""
    text = command.replace(str(repo) + "/", "")
    parts = text.split()
    if len(parts) > 1 and re.search(r"(^|/)(python[0-9.]*|node)$", parts[0]):
        parts = parts[1:]
        if len(parts) > 1 and parts[0] == "-m":
            parts = parts[1:]
    if parts and "/" in parts[0] and (parts[0].startswith(".venv/") or parts[0][0] != "."):
        parts[0] = Path(parts[0]).name
    text = " ".join(parts)
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass(frozen=True)
class ProcessSnapshot:
    procs: Mapping[int, Proc]
    names: Mapping[int, tuple[str, str]]
    project: frozenset[int]
    origins: Mapping[int, str]
    listeners: tuple[Listener, ...]
    self_pid: int
    taken_at: float
    error: str = ""
    guarded: frozenset[int] = frozenset()
    """Processes in the checkout that an editor, Claude Code or another agent runs: never
    stopped from here, only named, as another session's (:func:`guard_reason`)."""

    def listener_on(self, port: int) -> Listener | None:
        return next((item for item in self.listeners if item.port == port), None)

    def foreign(self) -> list[int]:
        """Project processes this panel did not start and no pid file of make accounts for, and
        what editors and agents run in the checkout."""
        return sorted(
            {
                pid
                for pid in self.project
                if self.origins.get(pid, "").startswith(("other", "control panel"))
            }
            | set(self.guarded)
        )

    def foreign_groups(self) -> list[list[Proc]]:
        """:meth:`foreign` by process group, the oldest group first."""
        groups: dict[int, list[Proc]] = defaultdict(list)
        for pid in self.foreign():
            proc = self.procs[pid]
            groups[proc.pgid].append(proc)
        return sorted(groups.values(), key=lambda m: min(p.pid for p in m))

    def foreign_summary(self, repo: Path) -> list[str]:
        """One line per process group of :meth:`foreign`, naming its top process."""
        return [describe_group(members, repo) for members in self.foreign_groups()]


def describe_group(members: Sequence[Proc], repo: Path) -> str:
    """A process group as one line: its make process, else its top process, with its pid, how
    long it has run and how many more processes the group has."""
    pids = {proc.pid for proc in members}
    top = next((p for p in members if p.ppid not in pids), members[0])
    maker = next((p for p in members if Path(p.command.split(" ", 1)[0]).name == "make"), top)
    if is_control_panel(top.command):
        text = f"another control panel window (pid {top.pid}, {format_seconds(top.elapsed)})"
    else:
        head = short_command(maker.command, repo, 48)
        text = f"{head} (pid {maker.pid}, {format_seconds(maker.elapsed)})"
    if len(members) > 1:
        text += f" with {len(members) - 1} more"
    return text


_USES_THE_PRODUCT = re.compile(r"product|playwright|\be2e\b|\bcw-(?:mvp|product)\b", re.I)
_USES_DOCKER = re.compile(
    r"\b(?:pytest|uvicorn|alembic|psql|pg_dump|pg_restore|docker|rpk|temporal|playwright|next)\b"
    r"|\bcw-(?:mvp|product|demo)\b|_service\b|\.(?:worker|relay)\b"
)
DOCKER_FREE_TARGETS: Final = frozenset(
    {
        "help", "check-uv", "check-pnpm", "py-sync", "lock-check", "py-lint", "py-format",
        "py-typecheck", "importlint", "ts-install", "ts-lint", "ts-format", "ts-typecheck",
        "ts-test", "ts-build", "install", "lint", "format", "typecheck", "runbooks-check",
        "openapi", "contracts", "contracts-check", "hooks", "ci-lint", "alerts-check",
        "openapi-check", "openapi-compat", "sast", "deps-scan", "ci-gate-check", "flags",
        "flags-check", "openapi-public", "openapi-ts", "openapi-ts-check", "web-screens",
        "web-screens-check",
    }
)  # fmt: skip
"""Make targets that need neither Docker nor the product: lint, format, type checks, unit tests
of the web app, contract and OpenAPI checks."""


def _make_targets(command: str) -> list[str] | None:
    """The targets of a make command line (empty: the default goal); None when it is not make."""
    parts = command.split()
    if not parts or Path(parts[0]).name not in ("make", "gmake"):
        return None
    return [part for part in parts[1:] if "=" not in part and not part.startswith("-")]


def _uses_docker(members: Sequence[Proc]) -> bool:
    """A group led by make uses Docker when one of its targets is not a Docker-free one (the
    tools a lint target runs say nothing); any other group, when it runs tests, services,
    migrations, the database's clients, the web app's dev server or the product."""
    makes = [targets for p in members if (targets := _make_targets(p.command)) is not None]
    if makes:
        return any(t not in DOCKER_FREE_TARGETS for targets in makes for t in targets)
    return bool(_USES_DOCKER.search(" ".join(proc.command for proc in members)))


@dataclass(frozen=True)
class StackUsers:
    """Other sessions' process groups in the checkout that need what a stop takes away."""

    docker: tuple[str, ...]
    product: tuple[str, ...]


def group_uses(members: Sequence[Proc]) -> tuple[str, ...]:
    """What a process group would lose in a stop: ``docker`` (its databases and queues) and
    ``product``. Another control panel window uses neither: it only reads."""
    commands = " ".join(proc.command for proc in members)
    if is_control_panel(commands):
        return ()
    uses: list[str] = []
    if _uses_docker(members):
        uses.append("docker")
    if _USES_THE_PRODUCT.search(commands):
        uses.append("product")
    return tuple(uses)


def stack_users(snapshot: ProcessSnapshot, repo: Path) -> StackUsers:
    """The foreign process groups that use Docker's databases and queues (tests, make targets,
    services, migrations, the web app) and those that use the product (make product and its
    checks, the browser journeys). Another control panel window is neither: it only reads."""
    docker: list[str] = []
    product: list[str] = []
    for members in snapshot.foreign_groups():
        uses = group_uses(members)
        text = describe_group(members, repo)
        if "product" in uses:
            product.append(text)
        if "docker" in uses:
            docker.append(text)
    return StackUsers(tuple(docker), tuple(product))


_AGENT = re.compile(r"(^|/)claude(\s|$)|Claude\.app|claude-code|/\.claude/", re.IGNORECASE)
_TERMINALS: Final = (
    "Terminal.app",
    "iTerm",
    "Ghostty",
    "WezTerm",
    "Alacritty",
    "kitty",
    "Warp.app",
    "tmux",
    "login -",
)


def session_kind(members: Sequence[Proc], procs: Mapping[int, Proc]) -> str:
    """Who runs a foreign process group: ``panel`` (another control window), ``agent`` (under
    Claude Code), ``terminal`` (under a terminal app), or ``other``."""
    if any(is_control_panel(proc.command) for proc in members):
        return "panel"
    pids = {proc.pid for proc in members}
    top = next((p for p in members if p.ppid not in pids), members[0])
    for pid in ancestors(top.pid, procs):
        command = procs[pid].command if pid in procs else ""
        if is_control_panel(command):
            return "panel"  # a run another control window started
        if _AGENT.search(command):
            return "agent"
        if any(name in command for name in _TERMINALS):
            return "terminal"
    return "other"


def breaks_note(users: StackUsers, *, docker: bool = False, product: bool = False) -> str:
    """What a confirm says about other sessions before it stops Docker or the product: each
    process group that uses them, by name, and plainly that the stop breaks them."""
    parts: list[str] = []
    if docker and users.docker:
        parts.append(
            "Other sessions are using Docker's databases and queues from this checkout right "
            "now. Stopping Docker will break them:\n  " + "\n  ".join(users.docker[:8])
        )
    if product and users.product:
        parts.append(
            "Other sessions are using the product right now. Stopping the product will break "
            "them:\n  " + "\n  ".join(users.product[:8])
        )
    return "\n\n".join(parts)


def pid_files(directory: Path) -> dict[str, int]:
    """The pid files of one directory (var/product, var/web-stack, var/control-panel) by name."""
    found: dict[str, int] = {}
    with contextlib.suppress(OSError):
        for path in sorted(directory.glob("*.pid")):
            pid = read_pid(path)
            if pid is not None:
                found[path.stem] = pid
    return found


def pid_file_owners(repo: Path) -> dict[int, str]:
    """The pids make product, make web-stack and this panel record, with who records them. The
    panel's own web app is the web.pid of var/web-stack; var/product's web.pid is make product's."""
    owners: dict[int, str] = {}
    for pid in pid_files(repo / "var" / "product").values():
        owners.setdefault(pid, "make product")
    for name, pid in pid_files(repo / "var" / "web-stack").items():
        owners.setdefault(pid, "panel web app" if name == "web" else "make web-stack")
    for pid in pid_files(repo / "var" / "control-panel").values():
        owners.setdefault(pid, "this panel")
    return owners


def process_origins(
    procs: Mapping[int, Proc],
    project: Collection[int],
    panel_groups: Collection[int],
    pid_files: Mapping[int, str],
    self_pid: int,
) -> dict[int, str]:
    """Who started each project process: this panel, a make target's pid file, another control
    panel window, or someone else (``other``)."""
    panels = {pid for pid in project if is_control_panel(procs[pid].command) and pid != self_pid}
    origins: dict[int, str] = {}
    for pid in project:
        proc = procs[pid]
        chain = [pid, *ancestors(pid, procs)]
        if pid == self_pid:
            origins[pid] = "this panel (the window)"
        elif proc.pgid in panel_groups or self_pid in chain[1:]:
            origins[pid] = "this panel"
        elif owner := next((pid_files[p] for p in chain if p in pid_files), ""):
            origins[pid] = owner
        elif pid in panels:
            origins[pid] = f"control panel {pid}"
        elif panel := next((p for p in [*chain[1:], proc.pgid] if p in panels), 0):
            origins[pid] = f"control panel {panel}"
        else:
            origins[pid] = "other"
    return origins


@dataclass(frozen=True)
class StopTarget:
    """What a stop sends SIGTERM to: a whole process group, or a process with its children;
    ``refused`` says why nothing may be signalled."""

    mode: Literal["group", "tree", "none"]
    pgid: int
    pids: tuple[int, ...]
    refused: str = ""


def _refusal(pid: int, snapshot: ProcessSnapshot) -> str:
    procs = snapshot.procs
    if pid not in procs:
        return f"pid {pid} is not running"
    if pid in {snapshot.self_pid, *ancestors(snapshot.self_pid, procs)}:
        return "that is this control panel or what started it"
    panels = control_panels(procs)
    if pid in panels:
        return "that is a control panel window; close it from the window itself"
    if pid in snapshot.guarded:
        who = snapshot.origins.get(pid, "").removeprefix("run by ") or "an editor or an agent"
        return f"{who} runs it; stop it there"
    if pid not in snapshot.project:
        return f"pid {pid} is not one of this checkout's processes"
    if any(child in panels for child in descendants(pid, procs)):
        return "a control panel window runs under it"
    return ""


def tree_target(pid: int, snapshot: ProcessSnapshot) -> StopTarget:
    """The process and those of its children that are the checkout's, or why none may be
    signalled: never this panel or what started it, never a control panel window, never a process
    outside the checkout."""
    proc = snapshot.procs.get(pid)
    pgid = proc.pgid if proc is not None else 0
    refused = _refusal(pid, snapshot)
    if refused:
        return StopTarget("none", pgid, (), refused)
    protected = {snapshot.self_pid, *ancestors(snapshot.self_pid, snapshot.procs)}
    panels = control_panels(snapshot.procs)
    tree = [pid, *descendants(pid, snapshot.procs)]
    pids = tuple(p for p in tree if p in snapshot.project and p not in protected | panels)
    return StopTarget("tree", pgid, pids)


def stop_options(pid: int, snapshot: ProcessSnapshot) -> list[StopTarget]:
    """What a stop of ``pid`` may signal: its process group when every member is the checkout's
    and none is a control panel window, and the process with its children; the group comes
    first. One refused target when nothing may be signalled."""
    branch = tree_target(pid, snapshot)
    if branch.refused:
        return [branch]
    procs = snapshot.procs
    proc = procs[pid]
    group = sorted(p.pid for p in procs.values() if p.pgid == proc.pgid)
    own_group = procs[snapshot.self_pid].pgid if snapshot.self_pid in procs else os.getpgrp()
    protected = {snapshot.self_pid, *ancestors(snapshot.self_pid, procs)}
    panels = control_panels(procs)
    if (
        proc.pgid > 1
        and proc.pgid != own_group
        and all(m in snapshot.project and m not in protected | panels for m in group)
    ):
        whole = StopTarget("group", proc.pgid, tuple(group))
        return [whole] if set(group) == set(branch.pids) else [whole, branch]
    return [branch]


def stop_target(pid: int, snapshot: ProcessSnapshot) -> StopTarget:
    """The first of :func:`stop_options`: the process group whenever it may be signalled."""
    return stop_options(pid, snapshot)[0]


def describe_stop(target: StopTarget, snapshot: ProcessSnapshot, repo: Path) -> str:
    if target.refused or not target.pids:
        return target.refused or "There is nothing of this checkout's to stop here."
    lines = []
    for pid in target.pids:
        proc = snapshot.procs.get(pid)
        if proc is not None:
            origin = snapshot.origins.get(pid, "other")
            lines.append(f"  {pid}  {short_command(proc.command, repo, 70)}  [{origin}]")
    if target.mode == "group":
        head = (
            f"Send SIGTERM to each process of group {target.pgid} named here ({len(target.pids)}):"
        )
    else:
        head = f"Send SIGTERM to pid {target.pids[0]} and its children ({len(target.pids)}):"
    return "\n".join([head, *lines])


STOP_GRACE_SECONDS: Final = 5.0
"""How long a stopped process gets to exit after SIGTERM before SIGKILL."""
WEB_STOP_GRACE_SECONDS: Final = 10.0
"""The web app's (next dev) grace: it writes its cache on the way out."""


@dataclass(frozen=True)
class StopResult:
    """What a stop did: the processes it signalled, and those it left alone because they started
    after the question (``new``) or run another program now (``changed``)."""

    signalled: tuple[int, ...]
    new: tuple[int, ...] = ()
    changed: tuple[int, ...] = ()

    @property
    def changed_since(self) -> bool:
        return bool(self.new or self.changed)


def stop_named(
    reach: Sequence[int],
    named: Mapping[int, str],
    snapshot: ProcessSnapshot,
    repo: Path,
    log: LogFn,
    wait: Callable[[float], bool],
    commands_now: Callable[[], Mapping[int, str]],
    *,
    kill: Callable[[int, int], None] | None = None,
    alive: Callable[[int], bool] | None = None,
    grace: float = STOP_GRACE_SECONDS,
) -> StopResult | None:
    """Stops what a question named and nothing else: each process in ``reach`` (what the stop
    would reach now, from a fresh scan) that ``named`` lists (pid and the program it ran when
    the question was asked) and that still runs that program. One ``os.kill`` per pid, never a
    process group: a process that joined the group since the question is not signalled. SIGKILL
    after ``grace`` to those still alive and still running the same program. What it leaves alone
    is logged by name. None when ``wait`` says the step was cancelled."""
    is_alive = alive or pid_alive
    send = kill or os.kill
    chosen: list[int] = []
    new: list[int] = []
    changed: list[int] = []
    for pid in reach:
        proc = snapshot.procs.get(pid)
        if pid not in named:
            new.append(pid)
        elif proc is None or proc.command != named[pid]:
            changed.append(pid)
        else:
            chosen.append(pid)
    for pid in new:
        command = (
            short_command(snapshot.procs[pid].command, repo, 70) if pid in snapshot.procs else ""
        )
        log(f"left alone, started after the question: pid {pid} {command}".rstrip(), None)
    for pid in changed:
        command = (
            short_command(snapshot.procs[pid].command, repo, 70) if pid in snapshot.procs else ""
        )
        log(f"left alone, runs another program now: pid {pid} {command}".rstrip(), None)
    if chosen:
        count = f"{len(chosen)} process{'es' if len(chosen) != 1 else ''}"
        log(f"SIGTERM to {count} the question named:", None)
        for pid in chosen:
            log(f"  {pid}  {short_command(named[pid], repo, 70)}", None)
    for pid in reversed(chosen):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            send(pid, signal.SIGTERM)
    for _ in range(max(int(grace / 0.25), 1)):
        if not any(is_alive(pid) for pid in chosen):
            break
        if not wait(0.25):
            return None
    if left := [pid for pid in chosen if is_alive(pid)]:
        now = commands_now()
        killed = [pid for pid in left if now.get(pid) == named[pid]]
        for pid in killed:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                send(pid, signal.SIGKILL)
        if killed:
            log(
                f"still running after {format_seconds(grace)}, sent SIGKILL: "
                + ", ".join(map(str, killed)),
                "err",
            )
    return StopResult(tuple(chosen), tuple(new), tuple(changed))


def changed_line(result: StopResult) -> str:
    """The error line of a stop that met processes its question did not name."""
    parts = []
    if result.new:
        count = len(result.new)
        parts.append(f"{count} process{'es' if count != 1 else ''} started after it")
    if result.changed:
        count = len(result.changed)
        parts.append(f"{count} now run{'s' if count == 1 else ''} another program")
    return (
        "error: changed since the question: "
        + " and ".join(parts)
        + "; they were left alone. Ask again to see what runs now."
    )


def stop_reach(pid: int, mode: Literal["group", "tree"], snapshot: ProcessSnapshot) -> StopTarget:
    """What a stop of ``pid`` in ``mode`` would reach now, or why it may not (no fallback from
    one mode to the other)."""
    options = stop_options(pid, snapshot)
    if options[0].refused:
        return options[0]
    if mode == "tree":
        return tree_target(pid, snapshot)
    found = next((option for option in options if option.mode == "group"), None)
    if found is None:
        proc = snapshot.procs[pid]
        return StopTarget("none", proc.pgid, (), "its process group may not be signalled whole now")
    return found


WEB_APP_MARKERS: Final = ("--filter web dev", "next dev", "next-server", "next start")


def web_app_root(pid: int, snapshot: ProcessSnapshot) -> int:
    """The top of a web app's own chain above its listener (next-server, next dev, the pnpm that
    runs them), never past a process that is not the web app's, such as make or a shell."""
    root = pid
    for parent in ancestors(pid, snapshot.procs):
        proc = snapshot.procs.get(parent)
        if proc is None or parent not in snapshot.project:
            break
        if not any(marker in proc.command for marker in WEB_APP_MARKERS):
            break
        root = parent
    return root


def web_stop_targets(
    project: Project, snapshot: ProcessSnapshot
) -> tuple[list[StopTarget], list[str]]:
    """What Stop web app signals, and what it leaves alone with why: the process tree of the web
    app the panel records (var/web-stack/web.pid, while that pid still runs it) and the process
    tree of whatever of this checkout listens on WEB_PORT, from the top of its web app chain.
    Never a process group: a make product whose web app holds the port keeps its app and
    worker, which share that group."""
    spec = project.web()
    roots: list[int] = []
    notes: list[str] = []
    recorded = read_pid(spec.pid_file)
    if recorded is not None:
        proc = snapshot.procs.get(recorded)
        if proc is not None and spec.marker in proc.command:
            roots.append(recorded)
        else:
            notes.append(f"var/web-stack/web.pid names pid {recorded}, which is not the web app")
    port = project.ports["WEB_PORT"]
    listener = snapshot.listener_on(port)
    if listener is not None:
        if listener.pid in snapshot.project:
            roots.append(web_app_root(listener.pid, snapshot))
        else:
            notes.append(f"port {port} is held by pid {listener.pid}, which is not this checkout's")
    targets: list[StopTarget] = []
    reached: set[int] = set()
    for root in roots:
        if root in reached:
            continue
        target = tree_target(root, snapshot)
        if target.refused:
            notes.append(f"pid {root} stays: {target.refused}")
            continue
        pids = tuple(pid for pid in target.pids if pid not in reached)
        if pids:
            targets.append(StopTarget("tree", target.pgid, pids))
            reached.update(pids)
    return targets, notes


# ---- what may run ------------------------------------------------------------------------------

FORBIDDEN_TARGETS: Final = frozenset({"backfill", "label"})
"""Targets that reach the live regulator sites (make backfill, make label ARGS="index ...")."""
FORBIDDEN_PROGRAMS: Final = frozenset(
    {"pipeline-backfill", "pipeline-label", "sh", "bash", "zsh", "dash", "fish"}
)
_REGULATOR_TOOLS: Final = frozenset({"pipeline-backfill", "pipeline-label"})
DESTRUCTIVE_TARGETS: Final = frozenset({"dev-reset", "dev-restore"})
_SAFE_VALUE = re.compile(r"[A-Z][A-Z0-9_]*=[A-Za-z0-9_./:@,+ -]*")


def command_problems(
    argv: Sequence[str],
    env: Mapping[str, str],
    *,
    known_targets: Collection[str] | None = None,
    confirmed: bool = False,
    complete_env: bool = False,
) -> list[str]:
    """Why one program must not run; empty when it may.

    No shell and no tool that reads the regulator sites; no --destructive, on the command line or
    in the environment; the crawl off (with ``complete_env``, ``env`` is the program's whole
    environment and must say so); none of :data:`DROPPED_VARIABLES`, which make would read;
    ``colima stop --force`` only when ``confirmed``; and for make: no forbidden target, no
    option, no shell character in a variable, product-seed without arguments, a destructive
    target only when ``confirmed``, and with ``known_targets`` only the checkout's targets.
    """
    if not argv:
        return ["no program"]
    problems: list[str] = []
    program = Path(argv[0]).name
    if program in FORBIDDEN_PROGRAMS:
        problems.append(f"runs {program}")
    problems += [
        f"runs {tool}" for tool in sorted({Path(part).name for part in argv[1:]} & _REGULATOR_TOOLS)
    ]
    if any("--destructive" in part for part in [*argv, *env.values()]):
        problems.append("passes --destructive")
    crawl = env.get("CW_PIPELINE_CRAWL_ENABLED")
    if (crawl is not None or complete_env) and crawl != "false":
        problems.append("does not keep the crawl off (CW_PIPELINE_CRAWL_ENABLED=false)")
    if inherited := sorted(set(env) & set(DROPPED_VARIABLES)):
        problems.append("carries " + ", ".join(inherited) + ", which make would read")
    forced = any(part in ("--force", "-f") for part in argv[1:])
    if program == "colima" and forced and not confirmed:
        problems.append("colima --force without a confirm")
    if program != "make":
        return problems
    targets = [part for part in argv[1:] if "=" not in part and not part.startswith("-")]
    variables = [part for part in argv[1:] if "=" in part]
    options = [part for part in argv[1:] if part.startswith("-")]
    problems += [f"make {t} is never run here" for t in targets if t in FORBIDDEN_TARGETS]
    problems += [f"unsafe make variable {v!r}" for v in variables if not _SAFE_VALUE.fullmatch(v)]
    if options:
        problems.append("make runs without options here: " + " ".join(options))
    if "product-seed" in targets and any(v.startswith("ARGS=") for v in variables):
        problems.append("product-seed runs with no arguments, against the product")
    if (
        "worker" in targets
        and "SERVICE=pipeline" in variables
        and env.get("CW_PIPELINE_CRAWL_ENABLED") != "false"
    ):
        problems.append("the pipeline worker runs only with the crawl off")
    if DESTRUCTIVE_TARGETS.intersection(targets) and not confirmed:
        problems.append("a destructive target without a confirm")
    if known_targets is not None:
        problems += [
            f"make {t} is not a target of this checkout's Makefile"
            for t in targets
            if t not in known_targets
        ]
    return problems


class RefusedError(Exception):
    """A program the rules of :func:`command_problems` do not let the panel run."""


class Capture(Protocol):
    """Runs a program to its end: :func:`run_capture`, or a step's own checked version of it."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        stdin_path: Path | None = None,
    ) -> tuple[int | None, str, str]: ...


PIPE_GRACE_SECONDS: Final = 2.0
"""How long the panel still reads a program's output once the program is gone or killed: a
process it left behind may hold the pipe open, and must not hold the panel."""


def kill_group(proc: subprocess.Popen[Any]) -> None:
    """SIGKILL to the process group a program the panel started leads (it starts a session of its
    own), so whatever it started goes with it."""
    # A group of our own: the program was started with start_new_session, so its group is a new
    # session that no process outside it can join (setpgid only moves a process within its own
    # session). It holds only what this program started.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        proc.kill()


def _output_after_kill(proc: subprocess.Popen[str]) -> tuple[str, str]:
    """What a killed program had written, read for :data:`PIPE_GRACE_SECONDS` at most."""
    try:
        out, err = proc.communicate(timeout=PIPE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=PIPE_GRACE_SECONDS)
        return "", ""
    return out or "", err or ""


def run_capture(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    stdin_path: Path | None = None,
) -> tuple[int | None, str, str]:
    """Run a program to its end and return its exit status and output; (None, output, why) when
    it is refused, missing or overruns the timeout. Every program the panel reads from runs
    through here, so the rules of :func:`command_problems` hold for each of them.

    The timeout is hard: the program starts a session of its own, and when it overruns, SIGKILL
    goes to its whole process group (``docker info`` hangs while Colima stops, and docker's
    plugins outlive a killed CLI); the wait for its output after that is bounded too."""
    problems = command_problems(argv, env, complete_env=True)
    if problems:
        return None, "", "refused: " + "; ".join(problems)
    try:
        with contextlib.ExitStack() as stack:
            stdin: Any = subprocess.DEVNULL
            if stdin_path is not None:
                stdin = stack.enter_context(stdin_path.open("rb"))
            proc = subprocess.Popen(
                list(argv),
                cwd=cwd,
                env=dict(env),
                stdin=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                kill_group(proc)
                out, err = _output_after_kill(proc)
                why = f"{Path(argv[0]).name} overran its {format_seconds(timeout)}; stopped"
                return None, out, f"{err}\n{why}".strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", str(exc)
    return proc.returncode, out, err


def spawn_detached(argv: Sequence[str], env: Mapping[str, str]) -> None:
    """Start a program that hands its work to macOS and exits (``open``), after the same checks."""
    problems = command_problems(argv, env, complete_env=True)
    if problems:
        raise RefusedError("; ".join(problems))
    subprocess.Popen(
        list(argv),
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def open_path(target: str | Path, env: Mapping[str, str], *, text_editor: bool = False) -> None:
    """Open a file, a folder or a URL with macOS's ``open`` (``-t``: the default text editor)."""
    spawn_detached(("open", "-t", str(target)) if text_editor else ("open", str(target)), env)


def lsof_program() -> str:
    return "/usr/sbin/lsof" if Path("/usr/sbin/lsof").exists() else "lsof"


def lsof_cwd_argv() -> tuple[str, ...]:
    return (lsof_program(), "-a", "-d", "cwd", "-u", str(os.getuid()), "+c", "0", "-Fpcn")


def lsof_listen_argv() -> tuple[str, ...]:
    return (lsof_program(), "-nP", "-iTCP", "-sTCP:LISTEN", "+c", "0", "-Fpcn")


def scan_commands() -> tuple[tuple[str, ...], ...]:
    """The programs a process scan runs: ps and the two lsof calls."""
    return (PS_ARGV, lsof_cwd_argv(), lsof_listen_argv())


def process_commands(env: Mapping[str, str], capture: Capture = run_capture) -> dict[int, str]:
    """Every process's command line by pid (one ps call); empty when ps cannot be read."""
    code, out, _ = capture(PS_ARGV, cwd=Path("/"), env=env, timeout=10)
    return {pid: proc.command for pid, proc in parse_ps(out).items()} if code == 0 else {}


DOCKER_INFO: Final = ("docker", "info")
COLIMA_STOP: Final = ("colima", "stop")
COLIMA_FORCE_STOP: Final = ("colima", "stop", "--force")
PG_RESTORE_LIST: Final = ("docker", "compose", "exec", "-T", "postgres", "pg_restore", "--list")

# How long each step of a stop may run before the panel stops it (SIGTERM to its process group,
# SIGKILL five seconds later) and marks it timed out.
WEB_STOP_SECONDS: Final = 60.0
MAKE_DOWN_SECONDS: Final = 120.0
BACKGROUND_STOP_SECONDS: Final = 60.0
DEV_DOWN_SECONDS: Final = 180.0
COLIMA_STOP_SECONDS: Final = 120.0
COLIMA_STOP_LABEL: Final = "stop Docker (colima stop)"
"""The step whose timeout makes the window offer ``colima stop --force``."""


def docker_running(repo: Path, env: Mapping[str, str], capture: Capture = run_capture) -> bool:
    return capture(DOCKER_INFO, cwd=repo, env=env, timeout=6)[0] == 0


# ---- what this panel started -------------------------------------------------------------------


def read_pid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return int(text) if text.isdigit() and int(text) > 1 else None


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def group_alive(pgid: int) -> bool:
    """A process of the group is left (a zombie counts until it is reaped)."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Registry:
    """The process group of every program this panel started (each step runs in a session of its
    own, so its children keep that group), in ``var/control-panel/registry.json``.

    Nothing is written until the panel starts something.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "registry.json"
        self._lock = threading.Lock()

    def _read(self) -> dict[str, Any]:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = {}
        groups = loaded.get("groups") if isinstance(loaded, dict) else None
        return {"version": 1, "groups": groups if isinstance(groups, dict) else {}}

    def _write(self, data: Mapping[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def add_group(self, pgid: int, label: str, argv: Sequence[str]) -> None:
        with self._lock, contextlib.suppress(OSError):
            data = self._read()
            data["groups"][str(pgid)] = {"label": label, "argv": list(argv), "started": time.time()}
            self._write(data)

    def groups(self) -> dict[int, str]:
        with self._lock:
            data = self._read()
        return {
            int(key): str(value.get("label", "")) if isinstance(value, dict) else ""
            for key, value in data["groups"].items()
            if str(key).isdigit()
        }

    def prune(self, live_pgids: Collection[int]) -> None:
        """Forget the groups no process is left in; writes only a registry that exists."""
        with self._lock:
            if not self.path.exists():
                return
            data = self._read()
            kept = {k: v for k, v in data["groups"].items() if k.isdigit() and int(k) in live_pgids}
            if kept != data["groups"]:
                data["groups"] = kept
                with contextlib.suppress(OSError):
                    self._write(data)


@dataclass(frozen=True)
class Background:
    """A long-running program the panel starts and stops itself: a worker, a relay, the web app.
    ``marker`` is what its command line holds, so a recycled pid is never taken for it."""

    key: str
    label: str
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...]
    pid_file: Path
    log_file: Path
    marker: str


NO_CRAWL: Final = (("CW_PIPELINE_CRAWL_ENABLED", "false"),)
"""Every worker and relay the panel starts runs with the crawl off, whatever .env says: a crawl
reads the live regulator sites (local-dev.md), which nothing the panel starts may do."""


def worker_spec(repo: Path, service: str) -> Background:
    key = f"worker-{service}"
    panel = repo / "var" / "control-panel"
    return Background(
        key,
        f"{service} worker",
        ("make", "worker", f"SERVICE={service}"),
        NO_CRAWL,
        panel / f"{key}.pid",
        panel / f"{key}.log",
        f"worker SERVICE={service}",
    )


def relay_spec(repo: Path, service: str) -> Background:
    key = f"relay-{service}"
    panel = repo / "var" / "control-panel"
    return Background(
        key,
        f"{service} outbox relay",
        ("make", "relay", f"SERVICE={service}"),
        NO_CRAWL,
        panel / f"{key}.pid",
        panel / f"{key}.log",
        f"relay SERVICE={service}",
    )


def web_spec(repo: Path, port: int) -> Background:
    """The UI-only web app; its pid and log stay in var/web-stack, where make web-stack-down
    stops it too, as they did before the panel grew tabs."""
    stack = repo / "var" / "web-stack"
    return Background(
        "web",
        "web app",
        ("pnpm", "--filter", "web", "dev"),
        (("PORT", str(port)),),
        stack / "web.pid",
        stack / "web.log",
        "--filter web dev",
    )


def has_worker(repo: Path, service: str) -> bool:
    source = repo / "services" / service / "src" / service_package(service)
    return (source / "worker.py").is_file() or (source / "worker" / "__main__.py").is_file()


def has_outbox(repo: Path, service: str) -> bool:
    versions = repo / "services" / service / "migrations" / "versions"
    with contextlib.suppress(OSError):
        for migration in sorted(versions.glob("*.py")):
            with contextlib.suppress(OSError, UnicodeDecodeError):
                if "outbox" in migration.read_text(encoding="utf-8"):
                    return True
    return False


type LogFn = Callable[[str, str | None], None]

KILL_GRACE_SECONDS: Final = 5.0


class BackgroundManager:
    """Starts a :class:`Background` in a session of its own, with its pid and log files, and
    stops it by signalling that session's process group.

    A pid read from a file that this window did not spawn counts only while its command line
    still holds the spec's marker, so a recycled pid neither reads as running nor blocks a start.
    """

    def __init__(
        self,
        repo: Path,
        env: Mapping[str, str],
        registry: Registry,
        known_targets: Collection[str] | None = None,
    ) -> None:
        self.repo = repo
        self.env = dict(env)
        self.registry = registry
        self.known_targets = known_targets
        self._children: dict[int, subprocess.Popen[bytes]] = {}
        self._lock = threading.Lock()

    def _recorded(self, spec: Background) -> tuple[int | None, bool]:
        """The pid file's pid while it lives, and whether this window spawned it."""
        pid = read_pid(spec.pid_file)
        if pid is None:
            return None, False
        with self._lock:
            child = self._children.get(pid)
        if child is not None:
            if child.poll() is None:
                return pid, True
            with self._lock:
                self._children.pop(pid, None)
            return None, True
        return (pid if pid_alive(pid) else None), False

    def live_pid(self, spec: Background, capture: Capture = run_capture) -> int | None:
        pid, ours = self._recorded(spec)
        if pid is None or ours:
            return pid
        commands = process_commands(self.env, capture)
        if not commands:
            return pid  # ps could not be read: keep the pid rather than start a second copy
        return pid if spec.marker in commands.get(pid, "") else None

    def states(
        self, specs: Sequence[Background], capture: Capture = run_capture
    ) -> dict[str, int | None]:
        """The live pid of each spec, with one ps call for every pid an earlier window recorded."""
        found: dict[str, int | None] = {}
        recorded: dict[str, int] = {}
        for spec in specs:
            pid, ours = self._recorded(spec)
            found[spec.key] = pid
            if pid is not None and not ours:
                recorded[spec.key] = pid
        if recorded:
            commands = process_commands(self.env, capture)
            for spec in specs:
                pid = recorded.get(spec.key)
                if commands and pid is not None and spec.marker not in commands.get(pid, ""):
                    found[spec.key] = None
        return found

    def start(self, spec: Background, log: LogFn, capture: Capture = run_capture) -> int | None:
        env = {**self.env, **dict(spec.env)}
        problems = command_problems(
            spec.argv, env, known_targets=self.known_targets, complete_env=True
        )
        if problems:
            log(f"error: {spec.label} refused: {'; '.join(problems)}", "err")
            return None
        running = self.live_pid(spec, capture)
        if running is not None:
            log(f"{spec.label} is already running (pid {running})", None)
            return running
        spec.log_file.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with spec.log_file.open("ab") as out:
                out.write(f"\n---- {stamp} {spec.label}: {shlex.join(spec.argv)}\n".encode())
                out.flush()
                proc = subprocess.Popen(
                    list(spec.argv),
                    cwd=self.repo,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        except OSError as exc:
            log(f"error: cannot start {spec.label}: {exc.strerror or exc}", "err")
            return None
        spec.pid_file.parent.mkdir(parents=True, exist_ok=True)
        spec.pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")
        with self._lock:
            self._children[proc.pid] = proc
        self.registry.add_group(proc.pid, spec.label, spec.argv)
        log(
            f"{spec.label} started (pid {proc.pid}, log {spec.log_file.relative_to(self.repo)})",
            "ok",
        )
        return proc.pid

    def stop(
        self, spec: Background, log: LogFn, grace: float = 10.0, capture: Capture = run_capture
    ) -> bool:
        pid, ours = self._recorded(spec)
        if pid is not None and not ours:
            commands = process_commands(self.env, capture)
            if not commands:
                log(f"{spec.label}: cannot read what pid {pid} runs; left alone", "err")
                return False
            if spec.marker not in commands.get(pid, ""):
                log(
                    f"{spec.label} is not running: pid {pid} of its pid file runs another program",
                    None,
                )
                spec.pid_file.unlink(missing_ok=True)
                return True
        if pid is None:
            spec.pid_file.unlink(missing_ok=True)
            log(f"{spec.label} is not running", None)
            return True
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            spec.pid_file.unlink(missing_ok=True)
            log(f"{spec.label} is not running", None)
            return True
        # The group only when the process leads one of its own: a panel starts each background
        # program with start_new_session, a new session no outside process can join, so the group
        # holds what that program started and nothing else (its marker was checked above).
        group = pgid == pid and pgid != os.getpgrp()
        with contextlib.suppress(ProcessLookupError):
            if group:
                os.killpg(pgid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and self._recorded(spec)[0] is not None:
            time.sleep(0.25)
        left = group_alive(pgid) if group else pid_alive(pid)
        if left:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                if group:
                    os.killpg(pgid, signal.SIGKILL)
                else:
                    os.kill(pid, signal.SIGKILL)
            log(f"{spec.label}: still running after {grace:.0f} s; sent SIGKILL", "err")
        self._recorded(spec)
        spec.pid_file.unlink(missing_ok=True)
        log(f"{spec.label} stopped (pid {pid})", "ok")
        return True


# ---- probes ------------------------------------------------------------------------------------

_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="probe")
"""The health checks' threads, kept between probes: eight answer every URL of a probe within its
deadline (a URL that does not answer gives up after 0.8 s), and bound the helper's threads."""


def http_ok(url: str, timeout: float = 0.8) -> bool:
    """True when the URL answers below 400 (no proxy: every URL the panel probes is local)."""
    try:
        with _LOCAL.open(url, timeout=timeout) as response:
            return int(response.status) < 400
    except (OSError, ValueError, http.client.HTTPException):
        return False


@dataclass(frozen=True)
class Status:
    docker: bool
    containers: Mapping[str, Container]
    up: Mapping[str, bool]
    background: Mapping[str, int | None]
    product_pids: Mapping[str, int | None]
    taken_at: float
    llm_provider: str | None = None
    """The model provider of the running product's gateway (``fake``, ``vercel``), from its
    log; None while the product is not running or its log does not say."""

    @property
    def infra_up(self) -> int:
        return sum(1 for name in INFRA if (c := self.containers.get(name)) is not None and c.up)


def status_urls(ports: Ports) -> dict[str, str]:
    """What the quick status probe asks, by key."""
    urls = {
        f"service:{name}": f"http://localhost:{ports.service(name)}/health" for name in SERVICES
    }
    urls["web"] = f"http://localhost:{ports['WEB_PORT']}"
    urls["product.internal"] = f"http://127.0.0.1:{ports['CW_MVP_INTERNAL_PORT']}/ready"
    urls["product.public"] = f"http://127.0.0.1:{ports['CW_MVP_PUBLIC_PORT']}/health"
    urls["product.worker"] = f"http://127.0.0.1:{ports['PRODUCT_WORKER_PORT']}/health"
    urls["product.web"] = f"http://127.0.0.1:{PRODUCT_WEB_PORT}/api/health"
    return urls


def _answered(future: Any, seconds: float) -> bool:
    try:
        return bool(future.result(timeout=seconds))
    except FutureTimeoutError:
        return False


_PROVIDER = re.compile(r"[a-z][a-z0-9_-]{0,31}")


def gateway_provider(log: Path, limit: int = 256 * 1024) -> str | None:
    """The provider the product's gateway said it wired, from the last ``gateway_wired`` line of
    its log (read from at most its last ``limit`` bytes); None when the log does not say."""
    try:
        with log.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(size - limit, 0))
            text = handle.read().decode("utf-8", "replace")
    except OSError:
        return None
    for line in reversed(text.splitlines()):
        if '"gateway_wired"' not in line:
            continue
        with contextlib.suppress(ValueError):
            entry = json.loads(line)
            provider = entry.get("provider") if isinstance(entry, dict) else None
            if isinstance(provider, str) and _PROVIDER.fullmatch(provider):
                return provider
        return None
    return None


def probe_status(project: Project, manager: BackgroundManager) -> Status:
    """The quick probe the window repeats every few seconds: Docker, the containers, each
    service's and listener's health, and the background processes. Every part has a hard limit:
    6 s for docker info, 8 s for docker compose ps, 0.8 s a URL (5 s for all of them)."""
    urls = status_urls(project.ports)
    pending = {key: _POOL.submit(http_ok, url) for key, url in urls.items()}
    docker = docker_running(project.repo, project.env)
    containers: dict[str, Container] = {}
    if docker:
        code, out, _ = run_capture(
            compose("ps", "-a", "--format", "json"), cwd=project.repo, env=project.env, timeout=8
        )
        if code == 0:
            containers = parse_compose_ps(out)
    deadline = time.monotonic() + 5.0
    up = {
        key: _answered(future, max(deadline - time.monotonic(), 0.0))
        for key, future in pending.items()
    }
    background = manager.states(project.backgrounds())
    product = {
        proc: (
            pid
            if (pid := read_pid(project.product_dir / f"{proc}.pid")) and pid_alive(pid)
            else None
        )
        for proc in ("app", "worker", "web")
    }
    provider = (
        gateway_provider(project.product_dir / "app.log") if up.get("product.internal") else None
    )
    return Status(docker, containers, up, background, product, time.time(), provider)


def probe_git(repo: Path, env: Mapping[str, str]) -> GitState:
    """The code the stack runs, read without taking a lock (git --no-optional-locks)."""
    git = ("git", "--no-optional-locks", "-C", str(repo))
    quiet = {**env, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}

    def read(*args: str) -> tuple[bool, str]:
        code, out, err = run_capture((*git, *args), cwd=repo, env=quiet, timeout=15)
        return code == 0, (out if code == 0 else err).strip()

    ok, branch = read("rev-parse", "--abbrev-ref", "HEAD")
    if not ok:
        return GitState(error=branch or "git cannot read this checkout")
    _, sha = read("rev-parse", "--short", "HEAD")
    status_ok, status = read("status", "--porcelain=v1", "--untracked-files=normal")
    counts_ok, counts = read("rev-list", "--left-right", "--count", "origin/main...HEAD")
    _, last = read("log", "-1", "--format=%s%x1f%cr")
    subject, _, when = last.partition("\x1f")
    ahead_behind = parse_ahead_behind(counts) if counts_ok else None
    return GitState(
        branch=branch,
        sha=sha,
        dirty=count_porcelain(status) if status_ok else 0,
        ahead=ahead_behind[0] if ahead_behind else None,
        behind=ahead_behind[1] if ahead_behind else None,
        subject=subject,
        when=when,
    )


def probe_remote(repo: Path, env: Mapping[str, str]) -> str | None:
    code, out, _ = run_capture(
        ("git", "--no-optional-locks", "-C", str(repo), "remote", "get-url", "origin"),
        cwd=repo,
        env=env,
        timeout=10,
    )
    return github_url(out) if code == 0 else None


def probe_processes(
    repo: Path, env: Mapping[str, str], registry: Registry, capture: Capture = run_capture
) -> ProcessSnapshot:
    """Every process with its name and working directory, the checkout's among them, who started
    each, and the listening sockets: ps and lsof, a heavy probe the window runs slowly."""
    root = Path("/")
    errors: list[str] = []
    code, out, err = capture(PS_ARGV, cwd=root, env=env, timeout=10)
    procs = parse_ps(out) if code == 0 else {}
    if code != 0:
        errors.append(f"ps: {err.strip() or 'failed'}")
    _, out, _ = capture(lsof_cwd_argv(), cwd=root, env=env, timeout=15)
    names = parse_lsof_cwd(out)
    _, out, _ = capture(lsof_listen_argv(), cwd=root, env=env, timeout=15)
    listeners = tuple(parse_lsof_listen(out))
    self_pid = os.getpid()
    project, guarded = split_guarded(project_pids(procs, names, repo), procs, self_pid)
    registry.prune({proc.pgid for proc in procs.values()})
    origins = process_origins(procs, project, registry.groups(), pid_file_owners(repo), self_pid)
    origins.update({pid: f"run by {who}" for pid, who in guarded.items()})
    return ProcessSnapshot(
        procs,
        names,
        frozenset(project),
        origins,
        listeners,
        self_pid,
        time.time(),
        "; ".join(errors),
        frozenset(guarded),
    )


@dataclass(frozen=True)
class KafkaSnapshot:
    groups: tuple[GroupLag, ...] = ()
    topics: tuple[TopicInfo, ...] = ()
    error: str = ""
    taken_at: float = 0.0


KAFKA_MIN_SECONDS: Final = 30.0
"""rpk runs at most once every 30 seconds, however often the Pipeline tab asks."""


def probe_kafka(repo: Path, env: Mapping[str, str]) -> KafkaSnapshot:
    """Consumer groups with their lag and the topics with their message counts, read only through
    rpk in the Redpanda container (on demand, at most every :data:`KAFKA_MIN_SECONDS`)."""
    errors: list[str] = []
    groups: list[GroupLag] = []
    topics: list[TopicInfo] = []
    code, out, err = run_capture(
        (*RPK, "group", "describe", "--format", "json", "-r", ".*"), cwd=repo, env=env, timeout=20
    )
    try:
        groups = parse_rpk_groups(out) if code == 0 else []
    except ValueError:
        code = 1
    if code != 0:
        errors.append("groups: " + (err.strip().splitlines() or ["rpk failed"])[-1])
    code, out, err = run_capture(
        (*RPK, "topic", "describe", "-p", "--format", "json", "-r", ".*"),
        cwd=repo,
        env=env,
        timeout=20,
    )
    try:
        topics = parse_rpk_topics(out) if code == 0 else []
    except ValueError:
        code = 1
    if code != 0:
        errors.append("topics: " + (err.strip().splitlines() or ["rpk failed"])[-1])
    return KafkaSnapshot(tuple(groups), tuple(topics), "; ".join(errors), time.time())


class RateLimit:
    """Lets something start at most once every ``seconds``, from any thread."""

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.seconds = seconds
        self.clock = clock
        self._last: float | None = None
        self._lock = threading.Lock()

    def wait(self) -> float:
        """0 when it may start now (and it is counted as started), else the seconds to wait."""
        with self._lock:
            now = self.clock()
            if self._last is not None and now - self._last < self.seconds:
                return self.seconds - (now - self._last)
            self._last = now
            return 0.0

    def remaining(self) -> float:
        """The seconds until it may start again (0 when it may now), without counting a start."""
        with self._lock:
            if self._last is None:
                return 0.0
            return max(self.seconds - (self.clock() - self._last), 0.0)


def load_flags(repo: Path) -> tuple[list[FlagRow], str]:
    """The flag registry with the values .env (and the apps' own env files) set."""
    try:
        text = (repo / "packages" / "flags" / "registry.json").read_text(encoding="utf-8")
        files = [
            (".env", read_env_file(repo / ".env")),
            ("apps/web/.env.local", read_env_file(repo / "apps" / "web" / ".env.local")),
            ("apps/whatsapp-bot/.env", read_env_file(repo / "apps" / "whatsapp-bot" / ".env")),
        ]
        return flag_rows(text, files), ""
    except (OSError, ValueError) as exc:
        return [], f"cannot read packages/flags/registry.json: {exc}"


_SAFE_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.dump")


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "kB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


@dataclass(frozen=True)
class Dump:
    """A dump make dev-backup wrote: its path relative to the checkout, size and time."""

    path: str
    size: int
    modified: float

    def describe(self, now: float) -> str:
        age = format_seconds(max(now - self.modified, 0))
        return f"{Path(self.path).name}  ·  {format_size(self.size)}  ·  {age} ago"


def list_backups(repo: Path) -> list[Dump]:
    """The dumps in var/backups, newest first. An empty one is left out: make dev-backup creates
    the file before pg_dump writes to it, so a failed or cancelled backup leaves one behind."""
    dumps: list[Dump] = []
    with contextlib.suppress(OSError):
        for path in (repo / "var" / "backups").glob("*.dump"):
            if not path.is_file() or not _SAFE_FILE.fullmatch(path.name):
                continue
            stat = path.stat()
            if stat.st_size > 0:
                dumps.append(Dump(str(path.relative_to(repo)), stat.st_size, stat.st_mtime))
    return sorted(dumps, key=lambda dump: dump.modified, reverse=True)


def check_dump(
    repo: Path, env: Mapping[str, str], dump: str, capture: Capture = run_capture
) -> tuple[bool, str]:
    """Whether pg_restore reads the dump: ``pg_restore --list`` in the Postgres container, with the
    file on its standard input, as make dev-restore gives it."""
    code, out, err = capture(
        PG_RESTORE_LIST, cwd=repo, env=env, timeout=120, stdin_path=repo / dump
    )
    entries = [line for line in out.splitlines() if line.strip() and not line.startswith(";")]
    if code == 0 and entries:
        return True, f"pg_restore --list reads {len(entries)} entries from {dump}"
    reason = (err.strip().splitlines() or ["it lists nothing"])[-1]
    return False, f"{dump} is not a dump pg_restore can read: {reason}"


def psql_script(repo: Path, path_value: str) -> str:
    """The script Terminal runs for psql: make dev-psql in the checkout, with the panel's PATH."""
    return "\n".join(
        [
            "#!/bin/bash",
            "# Written by the ComplianceWatch control panel: psql into the dev database.",
            f"export PATH={shlex.quote(path_value)}",
            f"cd {shlex.quote(str(repo))} || exit 1",
            "exec make dev-psql",
            "",
        ]
    )


def open_psql_terminal(repo: Path, env: Mapping[str, str]) -> Path:
    script = repo / "var" / "control-panel" / "psql.command"
    argv = ("open", "-a", "Terminal", str(script))
    if problems := command_problems(argv, env, complete_env=True):
        raise RefusedError("; ".join(problems))
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(psql_script(repo, env.get("PATH", "")), encoding="utf-8")
    script.chmod(0o700)
    spawn_detached(argv, env)
    return script


BUILD_FILE: Final = "BUILD"


def read_build(directory: Path) -> dict[str, str]:
    """What install-app.sh wrote beside the copy of the panel it put in ComplianceWatch.app (when,
    the commit the files came from, their hash); empty for a panel run from a checkout."""
    return read_env_file(directory / BUILD_FILE)


def describe_build(info: Mapping[str, str]) -> str:
    """The panel build the window shows, so an old app can be told from a new one."""
    if not info:
        return "Panel: this checkout's tools/control-panel"
    commit = info.get("commit", "")
    if commit and commit != "none":
        origin = f"commit {commit}"
    else:
        origin = f"files {info.get('files', '?')}, no commit"
    return f"Panel build {info.get('built', '?')} · {origin}"


# ---- the checkout as the panel sees it ---------------------------------------------------------

VOLUMES_FALLBACK: Final = (
    *("postgres_data", "redis_data", "redpanda_data"),
    *("prometheus_data", "tempo_data", "grafana_data"),
)
"""origin/main's named volumes, for a checkout whose docker-compose.yml cannot be read."""
VOLUME_NOTES: Final[Mapping[str, str]] = {
    "postgres_data": (
        "Postgres: every service's schema and the audit rows, and the temporal, "
        "temporal_visibility, langfuse and unleash databases"
    ),
    "redis_data": "Redis",
    "redpanda_data": "Redpanda: every topic, its messages and the consumer groups' offsets",
    "prometheus_data": "Prometheus's metrics",
    "tempo_data": "Tempo's traces",
    "grafana_data": "Grafana's state",
}


def parse_compose_volumes(text: str) -> list[str]:
    """The named volumes a compose file declares (its top-level ``volumes:``)."""
    volumes: list[str] = []
    inside = False
    for line in text.splitlines():
        if re.match(r"^volumes:\s*(#.*)?$", line):
            inside = True
            continue
        if not inside or not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            break
        if match := re.match(r"^ {2}([A-Za-z0-9][A-Za-z0-9_.-]*):", line):
            volumes.append(match.group(1))
    return volumes


def compose_project_name(
    compose_text: str, env_file: Mapping[str, str], environ: Mapping[str, str], repo: Path
) -> str:
    """The name compose gives the stack: COMPOSE_PROJECT_NAME (the environment, then .env), else
    the file's own ``name:``, else the checkout's directory."""
    if name := environ.get("COMPOSE_PROJECT_NAME") or env_file.get("COMPOSE_PROJECT_NAME"):
        return name
    if match := re.search(r"^name:\s*([A-Za-z0-9][A-Za-z0-9_-]*)\s*$", compose_text, re.M):
        return match.group(1)
    return repo.name.lower()


@dataclass
class Project:
    """The checkout, its environment and what the panel reads from its files at start."""

    repo: Path
    env: dict[str, str]
    ports: Ports
    make_targets: dict[str, str]
    checks: list[str]
    check_steps: list[str]
    screens: list[ScreenEntry]
    workers: list[str]
    relays: list[str]
    notes: list[str] = field(default_factory=list)
    volumes: list[tuple[str, str]] = field(default_factory=list)
    """Each named volume make dev-reset removes: (its full name, the short name compose uses)."""

    @classmethod
    def load(cls, repo: Path | None = None, environ: Mapping[str, str] | None = None) -> Project:
        environ = os.environ if environ is None else environ
        repo = repo or repo_root(environ)
        notes: list[str] = []
        try:
            makefile = (repo / "Makefile").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            makefile = ""
            notes.append(f"no Makefile in {repo}: every make step will fail")
        try:
            check = (repo / "tools/demo/src/cw_demo/product/check.py").read_text(encoding="utf-8")
            steps = parse_check_steps(check) or list(CHECK_STEPS_FALLBACK)
        except (OSError, UnicodeDecodeError):
            steps = list(CHECK_STEPS_FALLBACK)
        try:
            screens_ts = (repo / "apps/web/src/shared/config/screens.ts").read_text(
                encoding="utf-8"
            )
            screens = parse_screens(screens_ts) or list(SCREENS_FALLBACK)
        except (OSError, UnicodeDecodeError):
            screens = list(SCREENS_FALLBACK)
        env_file = read_env_file(repo / ".env")
        try:
            compose_text = (repo / "docker-compose.yml").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            compose_text = ""
        names = parse_compose_volumes(compose_text) or list(VOLUMES_FALLBACK)
        stack = compose_project_name(compose_text, env_file, environ, repo)
        return cls(
            repo=repo,
            env=program_env(environ),
            ports=resolve_ports(env_file, environ),
            make_targets=parse_make_targets(makefile),
            checks=parse_checks(makefile),
            check_steps=steps,
            screens=screens,
            workers=[s for s in SERVICES if has_worker(repo, s)],
            relays=[s for s in SERVICES if has_outbox(repo, s)],
            notes=notes,
            volumes=[(f"{stack}_{name}", name) for name in names],
        )

    @property
    def known_targets(self) -> dict[str, str] | None:
        """The Makefile's targets, or None when it could not be read (nothing to check against)."""
        return self.make_targets or None

    @property
    def panel_dir(self) -> Path:
        return self.repo / "var" / "control-panel"

    @property
    def product_dir(self) -> Path:
        return self.repo / "var" / "product"

    @property
    def web_stack_dir(self) -> Path:
        return self.repo / "var" / "web-stack"

    @property
    def web_url(self) -> str:
        return f"http://localhost:{self.ports['WEB_PORT']}"

    @property
    def product_web_url(self) -> str:
        return f"http://127.0.0.1:{PRODUCT_WEB_PORT}"

    @property
    def product_internal_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['CW_MVP_INTERNAL_PORT']}"

    @property
    def product_worker_url(self) -> str:
        return f"http://127.0.0.1:{self.ports['PRODUCT_WORKER_PORT']}"

    def web(self) -> Background:
        return web_spec(self.repo, self.ports["WEB_PORT"])

    def backgrounds(self) -> list[Background]:
        """Every background process the panel can start, the web app first."""
        return [
            self.web(),
            *(worker_spec(self.repo, s) for s in self.workers),
            *(relay_spec(self.repo, s) for s in self.relays),
        ]


# ---- plans -------------------------------------------------------------------------------------


class StepContext(Protocol):
    """What a :class:`Call` step gets from the runner. Every program it runs, streamed or
    captured, must be one its Call declares."""

    def log(self, text: str, tag: str | None = None) -> None: ...

    def allows(self, argv: Sequence[str]) -> bool: ...

    def run(self, argv: Sequence[str], env: Iterable[tuple[str, str]] = ()) -> bool: ...

    def capture(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        stdin_path: Path | None = None,
    ) -> tuple[int | None, str, str]: ...

    def wait(self, seconds: float) -> bool: ...

    @property
    def cancelled(self) -> bool: ...


@dataclass(frozen=True)
class Cmd:
    """A program run in the foreground, its output streamed into the panel. Past ``timeout``
    seconds the runner stops it and marks the step timed out."""

    label: str
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...] = ()
    timeout: float | None = None


@dataclass(frozen=True)
class Call:
    """A step the panel performs itself. ``commands`` is every program it may run, streamed or
    captured, and ``env`` what it adds to their environment: the plan checks read them, and the
    runner refuses any other program the step tries to run. ``timeout`` bounds the whole step:
    its programs get what is left of it, and its waits end when it runs out."""

    label: str
    fn: Callable[[StepContext], bool]
    commands: tuple[tuple[str, ...], ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    timeout: float | None = None


type Step = Cmd | Call


def step_commands(step: Step) -> tuple[tuple[str, ...], ...]:
    if isinstance(step, Cmd):
        return (step.argv,) if step.argv else ()
    return step.commands


@dataclass(frozen=True)
class Plan:
    """What one button runs: steps in order, stopping at the first failure unless ``keep_going``.

    ``confirm`` is the question the window asks first; ``gates`` marks a plan whose steps are
    quality gates, whose results the Gates tab keeps.
    """

    title: str
    steps: tuple[Step, ...]
    keep_going: bool = False
    confirm: str | None = None
    gates: bool = False


def make(
    *args: str, label: str = "", env: Iterable[tuple[str, str]] = (), timeout: float | None = None
) -> Cmd:
    return Cmd(label or "make " + " ".join(args), ("make", *args), tuple(env), timeout)


def plan_problems(plan: Plan, known_targets: Collection[str] | None = None) -> list[str]:
    """Why a plan must not run; empty when it may: :func:`command_problems` for every program of
    every step (a Call's declared ones included), a destructive target only in a plan that asks
    first, and at least one step."""
    problems: list[str] = [] if plan.steps else [f"{plan.title}: nothing to run"]
    for step in plan.steps:
        if isinstance(step, Cmd) and not step.argv:
            problems.append(f"{step.label}: no program")
        env = dict(step.env)
        for argv in step_commands(step):
            problems += [
                f"{step.label}: {problem}"
                for problem in command_problems(
                    argv, env, known_targets=known_targets, confirmed=bool(plan.confirm)
                )
            ]
    return problems


@dataclass(frozen=True)
class Gate:
    target: str
    label: str
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...] = ()
    note: str = ""


def _gate(
    target: str, *args: str, label: str = "", env: tuple[tuple[str, str], ...] = (), note: str = ""
) -> Gate:
    return Gate(target, label or target, ("make", target, *args), env, note)


GATES: Final = (
    _gate("check", label="make check", note="every gate in CHECKS: what CI runs before Docker"),
    _gate("lint", note="ruff, eslint and prettier"),
    _gate("typecheck", note="mypy --strict and tsc"),
    _gate("test", note="pytest with the coverage gate, and vitest"),
    _gate(
        "py-test-integration",
        env=(("TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE", "/var/run/docker.sock"),),
        note="testcontainers; needs Docker",
    ),
    _gate("eval", "EVAL_PROFILE=ci", label="eval (ci)", note="the eval harness, ci profile"),
    _gate("eval-check", note="the golden set and world"),
    _gate("openapi-compat", note="specs against origin/main"),
    _gate("contracts-check", note="regenerates the clients, then diffs them"),
    _gate("alerts-check", note="promtool in Docker"),
    _gate("flags-check", note="the flag registry"),
    _gate("migrations-check", note="static migration lint"),
    _gate("sast", note="Semgrep in Docker; its packs need the network"),
    _gate("deps-scan", note="Trivy in Docker"),
    _gate("web-screens-check", note="docs/web/screens.md"),
    _gate("web-e2e", note="after make web-stack, web-stack-wait and web-seed"),
    _gate("ci-lint", note="actionlint and pre-commit"),
)

CI_ORDER: Final = (
    # the python job
    "lint",
    "typecheck",
    "test",
    "importlint",
    "lock-check",
    "openapi-check",
    "flags-check",
    # the evals job
    "eval-check",
    "eval",
    # the contracts job
    "contracts-check",
    "openapi-compat",
    # make check's web gates
    "web-screens-check",
    "openapi-ts-check",
    # the ops job
    "runbooks-check",
    "migrations-check",
    "ci-gate-check",
    "alerts-check",
    "ci-lint",
    # the integration, sast and dependency-scan jobs
    "py-test-integration",
    "sast",
    "deps-scan",
)
"""The order "run the CI gates in order" follows (.github/workflows/ci.yml's jobs). Not in it:
make check itself (its gates run one by one), web-e2e (it needs the seeded UI-only stack) and the
dev-stack job (product-check --destructive needs a database made for the run)."""


def ci_sequence(
    checks: Sequence[str], known_targets: Collection[str] | None = None
) -> tuple[Gate, ...]:
    """CI_ORDER, with any gate of make check that it lacks after make check's own gates, and
    without a gate the checkout's Makefile no longer has (with ``known_targets``)."""
    known = {gate.target: gate for gate in GATES}
    order = list(CI_ORDER)
    at = order.index("openapi-ts-check") + 1
    for name in checks:
        if name not in order and name not in ("check", "web-e2e"):
            order.insert(at, name)
            at += 1
    if known_targets is not None:
        order = [name for name in order if name in known_targets]
    return tuple(known.get(name) or _gate(name) for name in order)


class Plans:
    """The plan behind every button. Plans that start or stop processes use :class:`Call` steps
    that the background manager carries out."""

    def __init__(self, project: Project, manager: BackgroundManager) -> None:
        self.project = project
        self.manager = manager

    # helpers carried out by Call steps
    def _docker_up(self, ctx: StepContext) -> bool:
        if docker_running(self.project.repo, self.project.env, ctx.capture):
            ctx.log("Docker is already running")
            return True
        return ctx.run(COLIMA_START)

    def _dev_down(self, ctx: StepContext) -> bool:
        if not docker_running(self.project.repo, self.project.env, ctx.capture):
            ctx.log("Docker is already stopped (docker info does not answer)")
            return True
        return ctx.run(("make", "dev-down"))

    def _colima_stop(self, ctx: StepContext) -> bool:
        if not docker_running(self.project.repo, self.project.env, ctx.capture):
            ctx.log("Docker is already stopped (docker info does not answer)")
            return True
        return ctx.run(COLIMA_STOP)

    def docker_up(self) -> Call:
        return Call("start Docker", self._docker_up, (DOCKER_INFO, COLIMA_START))

    def dev_down_call(self) -> Call:
        return Call(
            "stop the dev stack's containers (make dev-down)",
            self._dev_down,
            (DOCKER_INFO, ("make", "dev-down")),
            timeout=DEV_DOWN_SECONDS,
        )

    def colima_stop_call(self) -> Call:
        return Call(
            COLIMA_STOP_LABEL,
            self._colima_stop,
            (DOCKER_INFO, COLIMA_STOP),
            timeout=COLIMA_STOP_SECONDS,
        )

    def _start_background(self, spec: Background, settle: float = 3.0) -> Call:
        def start(ctx: StepContext) -> bool:
            if not ctx.allows(spec.argv):
                return False
            pid = self.manager.start(spec, ctx.log, ctx.capture)
            if pid is None:
                return False
            if not ctx.wait(settle):
                return False
            if self.manager.live_pid(spec, ctx.capture) is None:
                ctx.log(f"{spec.label} exited at once; the end of its log:", "err")
                for line in tail_lines(spec.log_file, 15):
                    ctx.log("  " + line, None)
                return False
            return True

        return Call(f"start the {spec.label}", start, (spec.argv, PS_ARGV), spec.env)

    def _stop_background(self, spec: Background) -> Call:
        def stop(ctx: StepContext) -> bool:
            return self.manager.stop(spec, ctx.log, capture=ctx.capture)

        return Call(f"stop the {spec.label}", stop, (PS_ARGV,))

    def _start_web(self, ctx: StepContext) -> bool:
        url = self.project.web_url
        if http_ok(url):
            ctx.log(f"web app already running on {url}")
            return True
        spec = self.project.web()
        if not ctx.allows(spec.argv) or self.manager.start(spec, ctx.log, ctx.capture) is None:
            return False
        for _ in range(90):
            if http_ok(url):
                ctx.log(f"web app ready on {url}", "ok")
                return True
            if self.manager.live_pid(spec, ctx.capture) is None:
                break
            if not ctx.wait(1):
                return False
        ctx.log(f"error: the web app did not start; see {spec.log_file}", "err")
        return False

    def start_web_call(self) -> Call:
        web = self.project.web()
        return Call("start web app", self._start_web, (web.argv, PS_ARGV), web.env)

    def stop_web_call(self, expected: Mapping[int, str] | None = None) -> Call:
        """Stop web app: the trees :func:`web_stop_targets` finds in a fresh scan, signalled pid by
        pid (:func:`stop_named`), SIGKILL ten seconds later to what still runs the same program.
        With ``expected`` (the pids and programs the question named), only those: the step fails,
        naming them, when the web app now runs a process the question did not name."""

        def stop(ctx: StepContext) -> bool:
            repo = self.project.repo
            snapshot = probe_processes(repo, self.project.env, self.manager.registry, ctx.capture)
            targets, notes = web_stop_targets(self.project, snapshot)
            for text in notes:
                ctx.log(text)
            reach = [pid for target in targets for pid in target.pids]
            if not reach:
                ctx.log("the web app is not running")
            named = (
                dict(expected)
                if expected is not None
                else {pid: snapshot.procs[pid].command for pid in reach}
            )
            result = stop_named(
                reach,
                named,
                snapshot,
                repo,
                ctx.log,
                ctx.wait,
                lambda: process_commands(self.project.env, ctx.capture),
                grace=WEB_STOP_GRACE_SECONDS,
            )
            if result is None:
                return False
            recorded = read_pid(self.project.web().pid_file)
            if recorded is not None and not pid_alive(recorded):
                self.project.web().pid_file.unlink(missing_ok=True)
            if result.changed_since:
                ctx.log(changed_line(result), "err")
                return False
            return True

        return Call("stop web app", stop, scan_commands(), timeout=WEB_STOP_SECONDS)

    def _stop_all_background(self, ctx: StepContext) -> bool:
        ok = True
        for spec in self.project.backgrounds()[1:]:
            if self.manager.live_pid(spec, ctx.capture) is not None:
                ok = self.manager.stop(spec, ctx.log, capture=ctx.capture) and ok
        return ok

    def stop_all_background_call(self) -> Call:
        return Call(
            "stop the panel's workers and relays",
            self._stop_all_background,
            (PS_ARGV,),
            timeout=BACKGROUND_STOP_SECONDS,
        )

    def _product_ready(self, ctx: StepContext) -> bool:
        url = self.project.product_internal_url + "/ready"
        if http_ok(url, timeout=3):
            return True
        ctx.log(
            f"error: the product does not answer {url}; make product-seed runs only against the "
            "running product, so start it first",
            "err",
        )
        return False

    # overview
    def start_everything(self) -> Plan:
        return Plan(
            "start everything",
            (
                self.docker_up(),
                make("dev", label="start databases and queues"),
                make("migrate", label="migrate databases"),
                make("web-stack", "STORE=postgres", label="start services"),
                make("web-stack-wait", label="wait for services"),
                self.start_web_call(),
                Cmd(f"open {self.project.web_url}", ("open", self.project.web_url)),
            ),
        )

    def stop_everything(self, expected_web: Mapping[int, str] | None = None) -> Plan:
        return Plan(
            "stop everything",
            (
                self.stop_web_call(expected_web),
                make("web-stack-down", label="stop the UI-only stack", timeout=MAKE_DOWN_SECONDS),
                make(
                    "product-down", label="stop the product's processes", timeout=MAKE_DOWN_SECONDS
                ),
                self.stop_all_background_call(),
                self.dev_down_call(),
                self.colima_stop_call(),
            ),
            confirm=(
                "Stop everything: the web app, the UI-only stack (make web-stack-down), the "
                "product's processes (make product-down), the panel's workers and relays, the dev "
                "stack's containers (make dev-down; the data stays in the volumes) and Docker "
                "itself (colima stop). Each step has a time limit; if colima stop overruns its "
                f"{format_seconds(COLIMA_STOP_SECONDS)}, the panel offers a force stop."
            ),
        )

    def docker_start(self) -> Plan:
        return Plan("start Docker", (self.docker_up(),))

    def docker_stop(self) -> Plan:
        return Plan(
            "stop Docker",
            (Cmd(COLIMA_STOP_LABEL, COLIMA_STOP, timeout=COLIMA_STOP_SECONDS),),
            confirm=(
                "Stop Docker (colima stop)? Every container stops: Postgres, Redis, Redpanda and "
                "Temporal, for every session using them. The data stays in the volumes."
            ),
        )

    def colima_force_stop(self) -> Plan:
        return Plan(
            "force-stop Docker",
            (
                Cmd(
                    "force-stop Docker (colima stop --force)",
                    COLIMA_FORCE_STOP,
                    timeout=COLIMA_STOP_SECONDS,
                ),
            ),
            confirm=(
                f"colima stop did not finish within {format_seconds(COLIMA_STOP_SECONDS)}. "
                "Force-stop Docker (colima stop --force)? Colima's VM stops at once, with no "
                "graceful shutdown: the containers get no time to close their files, so Postgres "
                "replays its write-ahead log at the next start, and a write in flight is lost. "
                "Every session using Docker loses it."
            ),
        )

    def databases_start(self) -> Plan:
        return Plan("make dev", (make("dev"),))

    def databases_stop(self) -> Plan:
        return Plan("make dev-down", (make("dev-down", timeout=DEV_DOWN_SECONDS),))

    def ui_start(self) -> Plan:
        return Plan(
            "start the UI-only stack",
            (
                make("web-stack", "STORE=postgres"),
                make("web-stack-wait", label="wait for services"),
            ),
        )

    def ui_stop(self) -> Plan:
        return Plan("stop the UI-only stack", (make("web-stack-down", timeout=MAKE_DOWN_SECONDS),))

    def ui_restart(self) -> Plan:
        return Plan(
            "restart the UI-only stack",
            (
                make("web-stack-down", label="stop services"),
                make("web-stack", "STORE=postgres"),
                make("web-stack-wait", label="wait for services"),
            ),
        )

    def ui_wait(self) -> Plan:
        return Plan("wait for the UI-only stack", (make("web-stack-wait"),))

    def web_start(self) -> Plan:
        return Plan("start the web app", (self.start_web_call(),))

    def web_stop(self, expected: Mapping[int, str] | None = None) -> Plan:
        return Plan("stop the web app", (self.stop_web_call(expected),))

    # stack
    def dev_observability(self) -> Plan:
        return Plan("make dev-observability", (make("dev-observability"),))

    def dev_llm(self) -> Plan:
        return Plan("make dev-llm", (make("dev-llm"),))

    def dev_flags(self) -> Plan:
        return Plan("make dev-flags", (make("dev-flags"),))

    def dev_ps(self) -> Plan:
        return Plan("make dev-ps", (make("dev-ps"),))

    def container_logs(self, service: str) -> Plan:
        argv = compose("logs", "--no-color", "--tail", "200", service)
        return Plan(f"{service} logs", (Cmd(f"the last 200 lines of {service}", argv),))

    # services and workers
    def worker_start(self, service: str) -> Plan:
        spec = worker_spec(self.project.repo, service)
        return Plan(f"start the {spec.label}", (self._start_background(spec),))

    def worker_stop(self, service: str) -> Plan:
        spec = worker_spec(self.project.repo, service)
        return Plan(f"stop the {spec.label}", (self._stop_background(spec),))

    def relay_start(self, service: str) -> Plan:
        spec = relay_spec(self.project.repo, service)
        return Plan(f"start the {spec.label}", (self._start_background(spec),))

    def relay_stop(self, service: str) -> Plan:
        spec = relay_spec(self.project.repo, service)
        return Plan(f"stop the {spec.label}", (self._stop_background(spec),))

    def tail(self, title: str, path: Path) -> Plan:
        relative = (
            path.relative_to(self.project.repo) if path.is_relative_to(self.project.repo) else path
        )
        return Plan(
            title, (Cmd(f"the last 200 lines of {relative}", ("tail", "-n", "200", str(relative))),)
        )

    # product
    def product_start(self) -> Plan:
        return Plan(
            "start the product",
            (self.docker_up(), make("product", f"WEB_PORT={PRODUCT_WEB_PORT}")),
        )

    def product_stop(self) -> Plan:
        return Plan("stop the product", (make("product-down", timeout=MAKE_DOWN_SECONDS),))

    def product_wait(self) -> Plan:
        return Plan("wait for the product", (make("product-wait", f"WEB_PORT={PRODUCT_WEB_PORT}"),))

    def product_role(self) -> Plan:
        return Plan("make product-role", (make("product-role"),))

    def product_seed(self) -> Plan:
        return Plan(
            "seed the product",
            (Call("check the product answers", self._product_ready), make("product-seed")),
        )

    def product_check(self, step: str | None = None) -> Plan:
        if step is None:
            return Plan("make product-check", (make("product-check"),))
        if step in NEVER_STEPS or not re.fullmatch(r"[a-z][a-z0-9_-]*", step):
            return Plan(f"product-check --step {step}", ())
        return Plan(f"product check: {step}", (make("product-check", f"ARGS=--step {step}"),))

    def product_e2e(self) -> Plan:
        return Plan(
            "make product-e2e",
            (make("product-e2e", f"PRODUCT_E2E_PORT={PRODUCT_E2E_PORT}"),),
        )

    def product_logs(self, proc: str) -> Plan:
        return Plan(f"product {proc} log", (make("product-logs", f"PROC={proc}", "FOLLOW=0"),))

    def mvp_image(self) -> Plan:
        return Plan("make mvp-image", (make("mvp-image"),))

    def product_image(self) -> Plan:
        return Plan("make product-image", (self.docker_up(), make("product-image")))

    def product_image_down(self) -> Plan:
        return Plan("make product-image-down", (make("product-image-down"),))

    def product_image_logs(self, proc: str) -> Plan:
        return Plan(
            f"image product {proc} log", (make("product-image-logs", f"PROC={proc}", "FOLLOW=0"),)
        )

    # data
    def migrate(self, service: str | None = None) -> Plan:
        if service is None:
            return Plan("make migrate", (make("migrate"),))
        return Plan(f"migrate {service}", (make("migrate", f"SERVICE={service}"),))

    def migrations_catalog(self) -> Plan:
        return Plan("make migrations-catalog", (make("migrations-catalog"),))

    def data_quality(self) -> Plan:
        return Plan("make data-quality", (make("data-quality"),))

    def seed_check(self) -> Plan:
        return Plan("check the seed calendar", (make("seed", "SERVICE=rulebook", "ARGS=--check"),))

    def load_demo_data(self) -> Plan:
        return Plan(
            "load demo data",
            (
                make("seed", "SERVICE=rulebook", label="seed rulebook"),
                make("web-seed", label="seed the demo tenant (UI-only stack)"),
            ),
        )

    def demo(self) -> Plan:
        return Plan("make demo", (make("demo"),))

    def doctor(self) -> Plan:
        return Plan("make doctor", (make("doctor"),))

    def backup(self) -> Plan:
        return Plan("make dev-backup", (make("dev-backup"),))

    @property
    def database(self) -> str:
        return read_env_file(self.project.repo / ".env").get("POSTGRES_DB") or "compliancewatch"

    def restore(self, dump: str) -> Plan:
        if not _SAFE_FILE.fullmatch(Path(dump).name) or Path(dump).parent != Path("var/backups"):
            return Plan(f"restore {dump}", ())

        def readable(ctx: StepContext) -> bool:
            ok, text = check_dump(self.project.repo, self.project.env, dump, ctx.capture)
            ctx.log(text, None if ok else "err")
            return ok

        return Plan(
            f"restore {dump}",
            (
                Call("check that pg_restore reads the dump", readable, (PG_RESTORE_LIST,)),
                make("dev-restore", f"FILE={dump}"),
            ),
            confirm=(
                f"Restore {dump}: make dev-restore drops the database {self.database} (WITH "
                "FORCE, which ends every open connection: the UI-only stack, the product and any "
                "worker lose theirs) and creates it again from the dump. Everything written since "
                "the dump was taken is lost."
            ),
        )

    def reset(self, backup_first: bool) -> Plan:
        steps: list[Step] = []
        if backup_first:
            steps.append(make("dev-backup", label="back up the database first"))
        steps += [
            make("web-stack-down", label="stop the UI-only stack", timeout=MAKE_DOWN_SECONDS),
            make("product-down", label="stop the product's processes", timeout=MAKE_DOWN_SECONDS),
            self.stop_all_background_call(),
            make("dev-reset"),
            make("dev"),
            make("migrate"),
            make("seed", "SERVICE=rulebook", label="seed rulebook"),
        ]
        volumes = "\n".join(
            f"  {full}" + (f": {VOLUME_NOTES[name]}" if name in VOLUME_NOTES else "")
            for full, name in self.project.volumes
        )
        return Plan(
            "reset database",
            tuple(steps),
            confirm=(
                "Reset deletes all local data. It stops the UI-only stack, the product's processes "
                "and the panel's workers and relays; then make dev-reset removes every container "
                "of the stack with its anonymous volumes, and every named volume "
                f"docker-compose.yml declares:\n{volumes}\n"
                "make dev, make migrate and the seed calendar then start it empty."
            ),
        )

    # quality gates
    def gate(self, gate: Gate) -> Plan:
        return Plan(gate.label, (Cmd(gate.label, gate.argv, gate.env),), gates=True)

    def gates_in_order(self) -> Plan:
        sequence = ci_sequence(self.project.checks, self.project.known_targets)
        steps = tuple(Cmd(g.label, g.argv, g.env) for g in sequence)
        return Plan("the CI gates in order", steps, keep_going=True, gates=True)

    # pipeline and flags
    def crawl_report(self) -> Plan:
        return Plan("make crawl-report", (make("crawl-report"),))

    def flags_check(self) -> Plan:
        return Plan("make flags-check", (make("flags-check"),), gates=True)

    # processes
    def stop_process(
        self,
        pid: int,
        command: str,
        mode: Literal["group", "tree"] = "group",
        named: Mapping[int, str] | None = None,
    ) -> Plan:
        """Stop one process (``tree``: it and its children; ``group``: its process group), as
        its question named it: ``named``, the pids and programs the question listed. A fresh
        scan decides what still runs; only pids both named and found are signalled, one by one
        (:func:`stop_named`), and the step fails, naming them, when something new appeared."""
        listed = dict(named) if named is not None else {pid: command}

        def stop(ctx: StepContext) -> bool:
            repo = self.project.repo
            snapshot = probe_processes(repo, self.project.env, self.manager.registry, ctx.capture)
            proc = snapshot.procs.get(pid)
            if proc is None:
                ctx.log(f"pid {pid} is not running any more")
                return True
            if proc.command != command:
                ctx.log(
                    f"error: changed since the question: pid {pid} now runs another program; "
                    "left alone. Ask again to see what runs now.",
                    "err",
                )
                return False
            target = stop_reach(pid, mode, snapshot)
            if target.refused:
                ctx.log(f"error: {target.refused}", "err")
                return False
            result = stop_named(
                target.pids,
                listed,
                snapshot,
                repo,
                ctx.log,
                ctx.wait,
                lambda: process_commands(self.project.env, ctx.capture),
            )
            if result is None:
                return False
            if result.changed_since:
                ctx.log(changed_line(result), "err")
                return False
            if not ctx.wait(0.5):
                return False
            if left := [p for p in result.signalled if pid_alive(p)]:
                ctx.log(f"error: still running: {', '.join(map(str, left))}", "err")
                return False
            ctx.log("stopped", "ok")
            return True

        return Plan(f"stop pid {pid}", (Call(f"SIGTERM to pid {pid}", stop, scan_commands()),))

    def all_plans(self) -> list[Plan]:
        """Every plan a button or a pick list can start, for the plan checks."""
        return [
            self.start_everything(),
            self.stop_everything(),
            self.stop_everything(
                expected_web={4242: "node /opt/homebrew/bin/pnpm --filter web dev"}
            ),
            self.docker_start(),
            self.docker_stop(),
            self.colima_force_stop(),
            self.databases_start(),
            self.databases_stop(),
            self.ui_start(),
            self.ui_stop(),
            self.ui_restart(),
            self.ui_wait(),
            self.web_start(),
            self.web_stop(),
            self.dev_observability(),
            self.dev_llm(),
            self.dev_flags(),
            self.dev_ps(),
            *(self.container_logs(s.name) for s in COMPOSE_SERVICES),
            *(self.worker_start(s) for s in SERVICES),
            *(self.worker_stop(s) for s in SERVICES),
            *(self.relay_start(s) for s in SERVICES),
            *(self.relay_stop(s) for s in SERVICES),
            self.product_start(),
            self.product_stop(),
            self.product_wait(),
            self.product_role(),
            self.product_seed(),
            self.product_check(),
            *(self.product_check(step) for step in selectable_steps(self.project.check_steps)),
            self.product_e2e(),
            *(self.product_logs(p) for p in ("app", "worker", "web")),
            self.mvp_image(),
            self.product_image(),
            self.product_image_down(),
            *(self.product_image_logs(p) for p in ("app", "worker", "release")),
            self.migrate(),
            *(self.migrate(s) for s in SERVICES),
            self.migrations_catalog(),
            self.data_quality(),
            self.seed_check(),
            self.load_demo_data(),
            self.demo(),
            self.doctor(),
            self.backup(),
            self.restore("var/backups/20261006T101500Z.dump"),
            self.reset(backup_first=True),
            self.reset(backup_first=False),
            *(self.gate(g) for g in GATES),
            self.gates_in_order(),
            self.crawl_report(),
            self.flags_check(),
            self.stop_process(4242, "make check"),
            self.stop_process(4242, "make check", "tree"),
        ]


def tail_lines(path: Path, count: int) -> list[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(size - 16384, 0))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return [clean_line(line) for line in text.splitlines()[-count:]]


# ---- the runner --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Line:
    runner: str
    text: str
    tag: str | None


@dataclass(frozen=True)
class Begin:
    runner: str
    plan: Plan


type StepState = Literal["running", "ok", "failed", "timeout", "cancelled", "skipped"]
"""``timeout``: the step overran its own time limit and the runner stopped it."""


@dataclass(frozen=True)
class StepUpdate:
    runner: str
    plan: Plan
    index: int
    label: str
    state: StepState
    seconds: float


@dataclass(frozen=True)
class StepResult:
    label: str
    state: StepState
    seconds: float


@dataclass(frozen=True)
class End:
    runner: str
    plan: Plan
    ok: bool
    cancelled: bool
    results: tuple[StepResult, ...]


type RunnerEvent = Line | Begin | StepUpdate | End

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
_ERROR_WORDS = re.compile(r"\b(error|errors|failed|failure|fatal|traceback)\b", re.IGNORECASE)
_NO_ERRORS = re.compile(r"\b(0|no|zero)\s+(errors?|failures?|failed)\b", re.IGNORECASE)


def clean_line(raw: str) -> str:
    """One output line without colour codes, and only the last state of a progress line."""
    text = _ANSI.sub("", raw.rstrip("\n"))
    if "\r" in text:
        parts = [part for part in text.split("\r") if part.strip()]
        text = parts[-1] if parts else ""
    return text.rstrip()


def line_tag(text: str) -> str | None:
    return "err" if _ERROR_WORDS.search(text) and not _NO_ERRORS.search(text) else None


class _Context:
    """A :class:`StepContext` for one Call: the programs it runs must be ones it declares, and
    with a ``deadline`` (the Call's timeout) its programs get what is left of it and its waits
    end when it runs out."""

    def __init__(self, runner: Runner, call: Call, deadline: float | None = None) -> None:
        self._runner = runner
        self._call = call
        self._deadline = deadline

    def remaining(self) -> float | None:
        if self._deadline is None:
            return None
        return max(self._deadline - time.monotonic(), 0.0)

    @property
    def expired(self) -> bool:
        return self._deadline is not None and time.monotonic() >= self._deadline

    def log(self, text: str, tag: str | None = None) -> None:
        self._runner.line(text, tag)

    def allows(self, argv: Sequence[str]) -> bool:
        if tuple(argv) in self._call.commands:
            return True
        self._runner.line(
            f"error: refused: {self._call.label} does not declare {shlex.join(argv)}", "err"
        )
        return False

    def run(self, argv: Sequence[str], env: Iterable[tuple[str, str]] = ()) -> bool:
        if not self.allows(argv) or self.expired:
            return False
        return self._runner.execute(
            self._call.label, argv, (*self._call.env, *env), timeout=self.remaining()
        )

    def capture(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        stdin_path: Path | None = None,
    ) -> tuple[int | None, str, str]:
        if not self.allows(argv):
            return None, "", f"refused: {self._call.label} does not declare it"
        left = self.remaining()
        limit = timeout if left is None else max(min(timeout, left), 0.1)
        return run_capture(argv, cwd=cwd, env=env, timeout=limit, stdin_path=stdin_path)

    def wait(self, seconds: float) -> bool:
        left = self.remaining()
        if left is not None and left < seconds:
            self._runner.cancel_event.wait(left)
            return False
        return not self._runner.cancel_event.wait(seconds)

    @property
    def cancelled(self) -> bool:
        return self._runner.cancel_event.is_set() or self.expired


class Runner:
    """Runs one plan at a time on a thread of its own and streams its output as events.

    It refuses a plan :func:`plan_problems` finds anything wrong with, and checks every program
    again where it starts it. Each program starts a session of its own, so :meth:`cancel`, or a
    step overrunning its time limit, can end the running step's whole process group without
    touching the panel: SIGTERM, then SIGKILL after a grace period to whatever of the group is
    left. A step that overruns ends as ``timeout``.
    """

    def __init__(
        self,
        name: str,
        repo: Path,
        env: Mapping[str, str],
        emit: Callable[[RunnerEvent], None],
        registry: Registry | None = None,
        timeout: float | None = None,
        known_targets: Collection[str] | None = None,
    ) -> None:
        self.name = name
        self.repo = repo
        self.env = dict(env)
        self.emit = emit
        self.registry = registry
        self.timeout = timeout
        self.known_targets = known_targets
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._busy = False
        self._plan: Plan | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._timed_out = False

    @property
    def busy(self) -> bool:
        """A plan is running: its thread is alive (a thread that died without ending its plan
        does not count)."""
        with self._lock:
            return self._busy and (self._thread is None or self._thread.is_alive())

    @property
    def plan(self) -> Plan | None:
        with self._lock:
            return self._plan if self._busy else None

    def start(self, plan: Plan) -> bool:
        """Start ``plan`` on its own thread; False, with the reason as output, when it is refused
        or another plan is running."""
        problems = plan_problems(plan, self.known_targets)
        if problems:
            for problem in problems:
                self.line(f"error: refused: {problem}", "err")
            return False
        with self._lock:
            running = self._plan.title if self._busy and self._plan else None
            if running is None:
                self._busy, self._plan, self._thread = True, plan, None
        if running is not None:
            self.line(f"{running} is still running; wait for it or cancel it", "err")
            return False
        self.cancel_event.clear()
        thread = threading.Thread(target=self._work, args=(plan,), daemon=True, name=self.name)
        try:
            thread.start()
        except RuntimeError as exc:  # no thread to be had: the plan never starts
            with self._lock:
                self._busy, self._plan = False, None
            self.line(f"error: {plan.title} could not start: {exc}", "err")
            return False
        with self._lock:
            if self._plan is plan:
                self._thread = thread
        return True

    def cancel(self) -> bool:
        with self._lock:
            if not self._busy:
                return False
            proc = self._proc
        self.cancel_event.set()
        if proc is not None:
            self._terminate(proc)
        return True

    def line(self, text: str, tag: str | None = None) -> None:
        self.emit(Line(self.name, text, tag))

    def _terminate(self, proc: subprocess.Popen[bytes]) -> None:
        """SIGTERM to the step's process group, and SIGKILL after the grace period to whatever of
        the group is left, its first process gone or not."""
        # The step's own group: each step starts with start_new_session, a new session that no
        # process outside it can join, so the group holds only what the step started. Cancel and
        # the time limits may signal it whole; a stop of another session's process never does.
        pgid = proc.pid
        if proc.poll() is not None and not group_alive(pgid):
            return
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGTERM)

        def escalate() -> None:
            time.sleep(KILL_GRACE_SECONDS)
            if group_alive(pgid):
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(pgid, signal.SIGKILL)

        threading.Thread(target=escalate, daemon=True).start()

    def _expire(self, proc: subprocess.Popen[bytes], label: str, limit: float) -> None:
        self._timed_out = True
        self.line(
            f"error: {label} overran its {format_seconds(limit)}: SIGTERM to its process group, "
            f"SIGKILL {format_seconds(KILL_GRACE_SECONDS)} later if it is still running",
            "err",
        )
        self._terminate(proc)

    def execute(
        self,
        label: str,
        argv: Sequence[str],
        env: Iterable[tuple[str, str]] = (),
        timeout: float | None = None,
    ) -> bool:
        """Run one program to its end, streaming its lines; True when it exits 0. The program and
        its whole environment are checked first, whoever asks. Past ``timeout`` seconds (else the
        runner's own limit) the program's group is stopped and the step marked timed out."""
        if self.cancel_event.is_set():
            return False
        full_env = {**self.env, **dict(env)}
        with self._lock:
            confirmed = bool(self._plan is not None and self._plan.confirm)
        problems = command_problems(
            argv, full_env, known_targets=self.known_targets, confirmed=confirmed, complete_env=True
        )
        if problems:
            self.line(f"error: refused: {label}: {'; '.join(problems)}", "err")
            return False
        try:
            proc = subprocess.Popen(
                list(argv),
                cwd=self.repo,
                env=full_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            self.line(f"error: cannot run {argv[0]}: {exc.strerror or exc}", "err")
            return False
        with self._lock:
            self._proc = proc
        if self.cancel_event.is_set():
            self._terminate(proc)
        if self.registry is not None:
            self.registry.add_group(proc.pid, label, argv)
        limit = timeout if timeout is not None else self.timeout
        try:
            code = self._follow(proc, label, limit)
        finally:
            with self._lock:
                self._proc = None
        return code == 0 and not self.cancel_event.is_set() and not self._timed_out

    def _follow(self, proc: subprocess.Popen[bytes], label: str, limit: float | None) -> int:
        """Stream a program's lines until it ends, and stop it past ``limit``. Once it has
        exited, its output is read for :data:`PIPE_GRACE_SECONDS` more at most: a process it left
        behind may hold the pipe open, and must not hold the step."""
        stdout = proc.stdout
        assert stdout is not None
        fd = stdout.fileno()
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        rest = ""
        deadline = time.monotonic() + limit if limit else None
        exited_at: float | None = None
        while True:
            now = time.monotonic()
            if deadline is not None and now >= deadline and not self._timed_out:
                self._expire(proc, label, limit or 0.0)
            ready, _, _ = select.select([fd], [], [], 0.2)
            if ready:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                rest = self._lines(rest + decoder.decode(chunk))
                continue
            if proc.poll() is not None:
                exited_at = exited_at if exited_at is not None else now
                if now - exited_at >= PIPE_GRACE_SECONDS:
                    self.line("a process the step started still holds its output; not read", None)
                    break
        self._lines(rest + decoder.decode(b"", final=True) + "\n")
        stdout.close()
        while True:
            try:
                return proc.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                if deadline is not None and time.monotonic() >= deadline and not self._timed_out:
                    self._expire(proc, label, limit or 0.0)

    def _lines(self, text: str) -> str:
        """Stream every complete line of ``text`` (a newline, a carriage return or both end
        one) and return what is left of it."""
        *complete, rest = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        for raw in complete:
            cleaned = clean_line(raw)
            if cleaned:
                self.line(cleaned, line_tag(cleaned))
        return rest

    def _run_step(self, step: Step) -> bool:
        self._timed_out = False
        if isinstance(step, Cmd):
            return self.execute(step.label, step.argv, step.env, step.timeout)
        deadline = time.monotonic() + step.timeout if step.timeout else None
        context = _Context(self, step, deadline)
        ok = bool(step.fn(context))
        if context.expired and not self.cancel_event.is_set():
            if not self._timed_out:
                self.line(
                    f"error: {step.label} overran its {format_seconds(step.timeout or 0.0)}", "err"
                )
            self._timed_out = True
        return ok and not self._timed_out

    def _work(self, plan: Plan) -> None:
        results: list[StepResult] = []
        failed = False
        self.emit(Begin(self.name, plan))
        try:
            for index, step in enumerate(plan.steps):
                if self.cancel_event.is_set() or (failed and not plan.keep_going):
                    state: StepState = "cancelled" if self.cancel_event.is_set() else "skipped"
                    results.append(StepResult(step.label, state, 0.0))
                    self.emit(StepUpdate(self.name, plan, index, step.label, state, 0.0))
                    continue
                self.line(f"\n▸ {step.label}", "step")
                self.emit(StepUpdate(self.name, plan, index, step.label, "running", 0.0))
                started = time.monotonic()
                try:
                    ok = self._run_step(step)
                except Exception as exc:  # a defect in one step must not leave the panel busy
                    self.line(f"error: {step.label}: {exc!r}", "err")
                    ok = False
                seconds = time.monotonic() - started
                if self.cancel_event.is_set():
                    state = "cancelled"
                elif self._timed_out:
                    state = "timeout"
                else:
                    state = "ok" if ok else "failed"
                results.append(StepResult(step.label, state, seconds))
                self.emit(StepUpdate(self.name, plan, index, step.label, state, seconds))
                if state in ("failed", "timeout"):
                    failed = True
                    tail = "" if plan.keep_going else " — stopped here"
                    what = "timed out" if state == "timeout" else "failed"
                    self.line(f"✗ {step.label} {what} after {format_seconds(seconds)}{tail}", "err")
            cancelled = self.cancel_event.is_set()
            if len(plan.steps) > 1 and plan.keep_going:
                self._summary(plan, results)
            if cancelled:
                self.line(f"■ {plan.title} cancelled", "err")
            elif failed:
                self.line(f"✗ {plan.title} failed", "err")
            else:
                self.line(f"✓ {plan.title} done", "ok")
        finally:
            with self._lock:
                self._busy, self._plan, self._proc = False, None, None
            self.emit(
                End(
                    self.name,
                    plan,
                    not failed and not self.cancel_event.is_set(),
                    self.cancel_event.is_set(),
                    tuple(results),
                )
            )

    def _summary(self, plan: Plan, results: Sequence[StepResult]) -> None:
        passed = sum(1 for r in results if r.state == "ok")
        total = sum(r.seconds for r in results)
        self.line(
            f"\n{plan.title}: {passed} of {len(results)} passed in {format_seconds(total)}", "step"
        )
        marks = {
            "ok": "✓",
            "failed": "✗",
            "timeout": "✗",
            "cancelled": "■",
            "skipped": "·",
            "running": "…",
        }
        width = max(len(r.label) for r in results)
        for result in results:
            duration = format_seconds(result.seconds) if result.seconds else "not run"
            if result.state == "timeout":
                duration += ", timed out"
            self.line(
                f"  {marks[result.state]} {result.label.ljust(width)}  {duration}",
                "err"
                if result.state in ("failed", "timeout")
                else ("ok" if result.state == "ok" else None),
            )


# ---- one probe of each kind at a time ------------------------------------------------------------


class SingleFlight:
    """At most one probe of each kind in flight: :meth:`begin` refuses a kind that is running.
    Safe to use from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: set[str] = set()

    def begin(self, key: str) -> bool:
        with self._lock:
            if key in self._running:
                return False
            self._running.add(key)
            return True

    def end(self, key: str) -> None:
        with self._lock:
            self._running.discard(key)

    def running(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._running)
