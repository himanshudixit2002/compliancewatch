"""ComplianceWatch Control's local helper: the JSON API and event stream behind the window.

The window (the app shell's WKWebView, or a browser with ``--open``) shows ``ui/``; everything it
reads or runs goes through this process, which serves both on ``127.0.0.1`` only. ``API.md`` is
the contract.

- **Security**: a random port and a random token per launch; every ``/api`` request carries the
  token in ``X-Panel-Token``; the ``Host`` must be ``127.0.0.1:<port>`` and an ``Origin``, when
  sent, ``http://127.0.0.1:<port>``; no CORS; JSON bodies of at most 64 KiB. Actions run only
  through ``panel_core``'s checked runner, and anything that stops, changes or deletes needs a
  confirm token from a preview. The UI is never trusted: every rule is checked here again.
- **Speed**: one shared poller reads the stack (every 2 s while a window is connected, every
  15 s otherwise) into a cache the requests answer from; the event stream pushes changes, step
  progress, output and toasts. No request waits on a probe.
- **Lifetime**: it prints one hand-off line, ``{"port": ..., "token": ...}``, and exits when its
  standard input (a pipe from the shell) closes, when its parent exits, after ten minutes
  without a request, or on SIGTERM.

``--demo`` serves a fake core (``panel_demo``): canned data and simulated runs, no subprocess and
no signal. Standard library only.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import dataclasses
import hmac
import json
import os
import queue
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable

import panel_catalog as catalog
import panel_core as core

API_VERSION: Final = 1
MAX_BODY: Final = 64 * 1024
IDLE_EXIT_SECONDS: Final = 600.0
CONFIRM_SECONDS: Final = 120.0
TICKET_SECONDS: Final = 30.0
LAUNCH_SECONDS: Final = 30.0
"""How long a launch code works: the code an address carries instead of the token."""
PING_SECONDS: Final = 15.0
EVENT_BUFFER: Final = 500
CLIENT_QUEUE: Final = 1000
RUN_LINES: Final = 2000
RUN_HISTORY: Final = 50
OUTPUT_BATCH: Final = 200
OUTPUT_EVERY: Final = 0.1
CACHE_SECONDS: Final = 30.0
GITHUB_SECONDS: Final = 60.0
FIRST_READ_SECONDS: Final = 1.5
QUESTION_SCAN_SECONDS: Final = 15.0
"""How long a question about processes waits for its fresh scan (ps and lsof)."""
_QUESTION_POOL: Final = ThreadPoolExecutor(max_workers=2, thread_name_prefix="question-scan")
HERE: Final = Path(__file__).resolve().parent
UI_DIR: Final = HERE / "ui"
PREFS_ENV: Final = "CW_CONTROL_PREFS"
DEFAULT_PREFS_PATH: Final = (
    Path.home() / "Library" / "Application Support" / "ComplianceWatch Control" / "prefs.json"
)
STATIC_TYPES: Final[Mapping[str, str]] = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".webmanifest": "application/manifest+json",
}
CSP: Final = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; "
    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'none'"
)


def log(text: str) -> None:
    """A diagnostic line on stderr; never the token, never a query string."""
    sys.stderr.write(f"panel_server: {text}\n")
    sys.stderr.flush()


# ---- errors ------------------------------------------------------------------------------------


class ApiError(Exception):
    """A request the helper answers with an error, in the shape of API.md section 3."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        detail: str = "",
        fix: str = "",
        action: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail
        self.fix = fix
        self.action = action

    def body(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "detail": self.detail,
                "fix": self.fix,
                "action": self.action,
            }
        }


# ---- the event stream --------------------------------------------------------------------------


@dataclass(frozen=True)
class Event:
    id: int
    name: str
    data: str

    def frame(self) -> bytes:
        return f"id: {self.id}\nevent: {self.name}\ndata: {self.data}\n\n".encode()


def frame(name: str, data: Mapping[str, Any]) -> bytes:
    """An event without an id: the ones a connection gets for itself (hello, its first
    status), which a reconnect must not count."""
    return f"event: {name}\ndata: {dumps(data)}\n\n".encode()


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


class Subscriber:
    def __init__(self) -> None:
        self.queue: queue.Queue[Event | None] = queue.Queue(CLIENT_QUEUE)
        self.closed = False


class Hub:
    """Fans every event out to the connected streams and keeps the last ``EVENT_BUFFER`` for a
    reconnect's ``Last-Event-ID``. A stream that falls ``CLIENT_QUEUE`` events behind is
    closed; it reconnects and resumes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next = 1
        self._buffer: collections.deque[Event] = collections.deque(maxlen=EVENT_BUFFER)
        self._subscribers: set[Subscriber] = set()

    def publish(self, name: str, data: Mapping[str, Any]) -> int:
        text = dumps(data)
        with self._lock:
            event = Event(self._next, name, text)
            self._next += 1
            self._buffer.append(event)
            for sub in list(self._subscribers):
                try:
                    sub.queue.put_nowait(event)
                except queue.Full:
                    sub.closed = True
                    self._subscribers.discard(sub)
                    with contextlib.suppress(queue.Full):
                        sub.queue.get_nowait()
                        sub.queue.put_nowait(None)
            return event.id

    def subscribe(self, last_id: int | None) -> tuple[Subscriber, list[Event] | None]:
        """A new stream, with the events to replay after ``last_id``; None when that id is too
        old to replay (the stream then starts afresh)."""
        sub = Subscriber()
        with self._lock:
            replay: list[Event] | None = []
            if last_id is not None:
                oldest = self._buffer[0].id if self._buffer else self._next
                if last_id + 1 < oldest or last_id >= self._next:
                    replay = None
                else:
                    replay = [event for event in self._buffer if event.id > last_id]
            self._subscribers.add(sub)
        return sub, replay

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            self._subscribers.discard(sub)

    def count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def close_all(self) -> None:
        with self._lock:
            subscribers, self._subscribers = list(self._subscribers), set()
        for sub in subscribers:
            sub.closed = True
            with contextlib.suppress(queue.Full):
                sub.queue.put_nowait(None)


# ---- tokens: confirms and stream tickets -------------------------------------------------------


class Book:
    """Single-use secrets with a lifetime: the confirm tokens a preview gives (bound to an
    action and its parameters) and the tickets an EventSource client may use."""

    def __init__(self, prefix: str, seconds: float, clock: Callable[[], float]) -> None:
        self.prefix = prefix
        self.seconds = seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._items: dict[str, tuple[float, str, dict[str, Any]]] = {}

    def issue(self, key: str = "", extra: Mapping[str, Any] | None = None) -> str:
        token = self.prefix + secrets.token_urlsafe(18)
        now = self._clock()
        with self._lock:
            self._items = {k: v for k, v in self._items.items() if v[0] > now}
            if len(self._items) > 200:
                self._items.pop(next(iter(self._items)))
            self._items[token] = (now + self.seconds, key, dict(extra or {}))
        return token

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def take(self, token: object, key: str = "") -> dict[str, Any] | None:
        """The token's extra data once, when it is live and was issued for ``key``."""
        if not isinstance(token, str) or not token.startswith(self.prefix):
            return None
        with self._lock:
            item = self._items.pop(token, None)
        if item is None:
            return None
        expires, bound, extra = item
        if expires < self._clock() or not hmac.compare_digest(bound, key):
            return None
        return extra


def confirm_key(action_id: str, params: Mapping[str, Any]) -> str:
    return f"{action_id}\n{json.dumps(params, sort_keys=True, default=str)}"


# ---- prefs -------------------------------------------------------------------------------------

DEFAULT_PREFS: Final[Mapping[str, Any]] = {"tour_done": False, "last_view": "", "dismissed": []}
_VIEW = re.compile(r"[a-z0-9/_-]{0,64}")


class Prefs:
    """The UI's few preferences, outside the checkout (in memory for ``--demo``)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._memory: dict[str, Any] = dict(DEFAULT_PREFS)

    def get(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._read())

    def _read(self) -> dict[str, Any]:
        if self.path is None:
            return dict(self._memory)
        values = dict(DEFAULT_PREFS)
        with contextlib.suppress(OSError, ValueError):
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                with contextlib.suppress(ValueError):
                    values.update(validate_prefs(loaded))
        return values

    def update(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        clean = validate_prefs(changes)
        with self._lock:
            values = self._read()
            values.update(clean)
            if self.path is None:
                self._memory = values
            else:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_name(self.path.name + ".tmp")
                temporary.write_text(json.dumps(values, indent=1) + "\n", encoding="utf-8")
                temporary.replace(self.path)
            return dict(values)


def validate_prefs(changes: Mapping[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in changes.items():
        if (key == "tour_done" and isinstance(value, bool)) or (
            key == "last_view" and isinstance(value, str) and _VIEW.fullmatch(value)
        ):
            clean[key] = value
        elif (
            key == "dismissed"
            and isinstance(value, list)
            and len(value) <= 100
            and all(isinstance(item, str) and len(item) <= 80 for item in value)
        ):
            clean[key] = list(value)
        else:
            raise ValueError(f"{key!r} is not a preference, or its value is not allowed")
    return clean


# ---- what the helper needs from a core (the real one below, panel_demo's fake one) -------------


class RunnerLike(Protocol):
    @property
    def busy(self) -> bool: ...

    @property
    def plan(self) -> core.Plan | None: ...

    def start(self, plan: core.Plan) -> bool: ...

    def cancel(self) -> bool: ...


@runtime_checkable
class Preparable(Protocol):
    """A runner told which action its next plan is for (the demo's, for an armed failure)."""

    def prepare(self, action_id: str) -> None: ...


@runtime_checkable
class DemoControl(Protocol):
    """What ``POST /api/demo/state`` drives: only the ``--demo`` core has it."""

    def reset_world(self) -> None: ...

    def parse_state(self, body: Mapping[str, Any], actions: Collection[str]) -> Any: ...

    def apply_state(self, change: Any) -> None: ...

    def describe_world(self) -> dict[str, Any]: ...


class Backend(Protocol):
    """Everything the helper reads or does, from the real checkout or from canned data."""

    demo: bool
    build: str

    @property
    def project(self) -> core.Project: ...

    @property
    def plans(self) -> core.Plans: ...

    def probe_status(self) -> core.Status: ...

    def probe_processes(self) -> core.ProcessSnapshot: ...

    def probe_git(self) -> core.GitState: ...

    def probe_kafka(self) -> core.KafkaSnapshot: ...

    def flags(self) -> tuple[list[core.FlagRow], str]: ...

    def backups(self) -> list[core.Dump]: ...

    def compose_services(self) -> list[str]: ...

    def env_file_exists(self) -> bool: ...

    def features(
        self, status: core.Status | None, last_check: Mapping[str, Any] | None
    ) -> list[dict[str, Any]]: ...

    def github(self, git: core.GitState | None) -> dict[str, Any]: ...

    def log_sources(self) -> list[dict[str, Any]]: ...

    def read_log(self, source: str, tail: int) -> dict[str, Any]: ...

    def docs(self) -> list[dict[str, Any]]: ...

    def open_path(self, path: Path, text_editor: bool) -> None: ...

    def open_psql(self) -> str: ...

    def make_runner(self, name: str, emit: Callable[[core.RunnerEvent], None]) -> RunnerLike: ...


# ---- the views: panel_core's data in the API's shapes ------------------------------------------


def checkout_view(git: core.GitState | None) -> dict[str, Any] | None:
    if git is None:
        return None
    return {
        "branch": git.branch,
        "sha": git.sha,
        "subject": git.subject,
        "when": git.when,
        "dirty": git.dirty,
        "ahead": git.ahead,
        "behind": git.behind,
        "is_main": git.on_main,
        "error": git.error,
    }


KIND_WORDS: Final[Mapping[str, str]] = {
    "agent": "Claude's build agent",
    "terminal": "A terminal",
    "panel": "Another control window",
    "other": "Another session",
}


def sessions_view(snapshot: core.ProcessSnapshot | None, repo: Path) -> list[dict[str, Any]]:
    """Other sessions' process groups in the checkout, each with who runs it and what a stop
    would take from it."""
    if snapshot is None:
        return []
    sessions = []
    for members in snapshot.foreign_groups():
        pids = {proc.pid for proc in members}
        top = next((p for p in members if p.ppid not in pids), members[0])
        maker = next((p for p in members if Path(p.command.split(" ", 1)[0]).name == "make"), top)
        kind = core.session_kind(members, snapshot.procs)
        sessions.append(
            {
                "pid": maker.pid,
                "label": "another control window"
                if any(core.is_control_panel(proc.command) for proc in members)
                else core.short_command(maker.command, repo, 48),
                "elapsed": maker.elapsed,
                "kind": kind,
                "uses": list(core.group_uses(members)),
                "text": core.describe_group(members, repo),
            }
        )
    return sessions


def summarize(status: core.Status) -> tuple[str, str]:
    """The status in one plain sentence, and its level: running, partial or stopped."""
    services = sum(1 for name in core.SERVICES if status.up.get(f"service:{name}"))
    web = bool(status.up.get("web"))
    product = bool(status.up.get("product.internal"))
    infra = status.infra_up
    if not status.docker:
        return "stopped", "Everything is stopped. Docker is not running."
    parts = []
    if infra == len(core.INFRA):
        parts.append("the databases")
    if services == len(core.SERVICES):
        parts.append("the ten services")
    elif services:
        parts.append(f"{services} of the ten services")
    if web:
        parts.append("the web app")
    if product:
        parts.append("the product")
    everything = infra == len(core.INFRA) and services == len(core.SERVICES) and web
    if everything:
        text = "Everything is running: " + _join(parts) + "."
        return "running", text
    if not parts:
        return "partial", "Docker is running, but nothing else is."
    stopped = []
    if infra < len(core.INFRA):
        stopped.append("some databases")
    if services == 0:
        stopped.append("the services")
    if not web:
        stopped.append("the web app")
    text = f"{_join(parts).capitalize()} {_be(parts)} running"
    if stopped:
        text += f"; {_join(stopped)} {_be(stopped)} stopped"
    return "partial", text + "."


def _be(items: Sequence[str]) -> str:
    """The verb for a list of parts: "the web app is", "the databases are"."""
    return "is" if len(items) == 1 and not items[0].endswith("s") else "are"


def _join(items: Sequence[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def status_view(
    project: core.Project,
    status: core.Status | None,
    snapshot: core.ProcessSnapshot | None,
    git: core.GitState | None,
    *,
    demo: bool,
) -> dict[str, Any]:
    sessions = sessions_view(snapshot, project.repo)
    warnings = status_warnings(git, sessions)
    base: dict[str, Any] = {
        "taken_at": status.taken_at if status else None,
        "loading": status is None,
        "demo": demo,
        "checkout": checkout_view(git),
        "sessions": sessions,
        "warnings": warnings,
    }
    if status is None:
        return base | {
            "summary": "Reading what is running…",
            "level": "unknown",
            "docker": None,
            "infra": [],
            "services": [],
            "web": None,
            "product": None,
            "background": [],
        }
    ports = project.ports
    known = {service.name: service for service in core.COMPOSE_SERVICES}
    names = [s.name for s in core.COMPOSE_SERVICES if s.name in status.containers]
    names += sorted(set(status.containers) - set(known))
    infra = []
    for name in names:
        container = status.containers[name]
        service = known.get(name)
        infra.append(
            {
                "service": name,
                "label": service.what if service else name,
                "profile": (service.profile or "core") if service else "",
                "state": container.state,
                "health": container.health,
                "up": container.up,
                "ports": list(container.ports),
                "status": container.status,
                "exit_code": container.exit_code,
            }
        )
    level, summary = summarize(status)
    public = f"http://127.0.0.1:{ports['CW_MVP_PUBLIC_PORT']}"
    return base | {
        "summary": summary,
        "level": level,
        "docker": {"up": status.docker, "detail": "Colima"},
        "infra": infra,
        "services": [
            {
                "name": name,
                "port": ports.service(name),
                "up": bool(status.up.get(f"service:{name}")),
                "url": f"http://localhost:{ports.service(name)}",
                "docs_url": f"http://localhost:{ports.service(name)}/docs",
            }
            for name in core.SERVICES
        ],
        "web": {
            "up": bool(status.up.get("web")),
            "port": ports["WEB_PORT"],
            "url": project.web_url,
        },
        "product": {
            "internal": _listener(status, "product.internal", ports["CW_MVP_INTERNAL_PORT"]),
            "public": _listener(status, "product.public", ports["CW_MVP_PUBLIC_PORT"], public),
            "worker": _listener(status, "product.worker", ports["PRODUCT_WORKER_PORT"]),
            "web": _listener(status, "product.web", core.PRODUCT_WEB_PORT),
            "pids": dict(status.product_pids),
            "llm_provider": status.llm_provider,
        },
        "background": [
            {
                "key": spec.key,
                "label": spec.label,
                "kind": spec.key.split("-", 1)[0],
                "service": spec.key.split("-", 1)[1],
                "pid": status.background.get(spec.key),
            }
            for spec in project.backgrounds()[1:]
        ],
    }


def _listener(status: core.Status, key: str, port: int, url: str = "") -> dict[str, Any]:
    return {
        "up": bool(status.up.get(key)),
        "port": port,
        "url": url or f"http://127.0.0.1:{port}",
    }


def status_warnings(
    git: core.GitState | None, sessions: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """The status's standing warnings, in the preview's Warning shape: the branch when it is
    not main, and other sessions that use the stack."""
    warnings: list[dict[str, Any]] = []
    if git is not None and not git.error and git.branch and not git.on_main:
        warnings.append(
            {
                "code": "not-main",
                "tone": "warning",
                "title": f"This checkout is on {git.branch}, not main",
                "message": f"This checkout is on {git.branch}, not main: what you start runs that "
                "branch's code, and starting the stack applies its database changes to the "
                "shared development database.",
                "items": [],
            }
        )
    busy = [s for s in sessions if s["uses"]]
    if busy:
        first = busy[0]
        more = f", and {len(busy) - 1} more" if len(busy) > 1 else ""
        warnings.append(
            {
                "code": "sessions",
                "tone": "info",
                "title": "Other sessions are using this checkout",
                "message": f"{KIND_WORDS[first['kind']]} is using this checkout: "
                f"{first['text']}{more}.",
                "items": [f"{KIND_WORDS[s['kind']]}: {s['text']}" for s in busy],
            }
        )
    return warnings


def processes_view(project: core.Project, snapshot: core.ProcessSnapshot) -> dict[str, Any]:
    repo = project.repo
    ports = []
    for entry in core.port_catalogue(project.ports):
        listener = snapshot.listener_on(entry.port)
        proc = snapshot.procs.get(listener.pid) if listener else None
        command = ""
        if listener is not None:
            if listener.command == "ssh" and proc is not None and "colima" in proc.command:
                command = "ssh (Colima's port forwarding to the container)"
            else:
                command = core.short_command(proc.command if proc else listener.command, repo, 80)
        ports.append(
            {
                "port": entry.port,
                "what": entry.what,
                "group": entry.group,
                "url": entry.url,
                "pid": listener.pid if listener else None,
                "command": command,
                "origin": snapshot.origins.get(listener.pid, "") if listener else "",
            }
        )
    processes = []
    # what an editor or Claude Code runs in the checkout is listed too (its origin says who), so
    # the window can name it; it is never offered a stop
    for pid in sorted(snapshot.project | snapshot.guarded):
        proc = snapshot.procs[pid]
        origin = snapshot.origins.get(pid, "other")
        processes.append(
            {
                "pid": pid,
                "pgid": proc.pgid,
                "ppid": proc.ppid,
                "elapsed": proc.elapsed,
                "command": core.short_command(proc.command, repo, 110),
                "origin": origin,
                "kind": "this-app" if origin.startswith("this panel") else "other",
            }
        )
    return {
        "taken_at": snapshot.taken_at,
        "ports": ports,
        "processes": processes,
        "error": snapshot.error,
    }


def kafka_view(
    snapshot: core.KafkaSnapshot | None, next_in: float, reading: bool
) -> dict[str, Any]:
    return {
        "taken_at": snapshot.taken_at if snapshot else None,
        "groups": [
            {"group": g.group, "state": g.state, "members": g.members, "total_lag": g.total_lag}
            for g in (snapshot.groups if snapshot else ())
        ],
        "topics": [
            {
                "name": t.name,
                "partitions": t.partitions,
                "messages": t.messages,
                "dead_letters": t.dead_letters,
            }
            for t in (snapshot.topics if snapshot else ())
        ],
        "error": snapshot.error if snapshot else "",
        "next_in": max(round(next_in), 0),
        "reading": reading,
    }


# ---- what a failed run means, in plain words ---------------------------------------------------

_FAILURES: Final = (
    # what is not running comes first: a "Connection refused" from a client (psycopg, curl) is
    # never a refusal of the safety rules
    (
        re.compile(
            r"cannot connect to the docker daemon|is the docker daemon running|docker daemon is "
            r"not running|error during connect",
            re.I,
        ),
        "docker-down",
        "Docker is not running",
        "Start Docker, then try again.",
        "docker-start",
    ),
    (
        re.compile(
            r"product does not answer|ready.*not answer|"
            r"(?:port |:)(?:8080|8000|8081)\b.*(?:refused|failed)|"
            r"(?:refused|failed).*(?:port |:)(?:8080|8000|8081)\b",
            re.I,
        ),
        "product-down",
        "The product is not answering",
        "Start the product, then try again.",
        "product-start",
    ),
    (
        re.compile(
            r"(?:port |:)(?:5432|6379|19092|7233)\b.*(?:refused|failed)|"
            r"(?:refused|failed).*(?:port |:)(?:5432|6379|19092|7233)\b",
            re.I,
        ),
        "databases-down",
        "The databases are not answering",
        "Start the databases and queues, then try again.",
        "databases-start",
    ),
    (
        re.compile(r"refused: CW_PIPELINE_EXTRACTION_ENABLED is off", re.I),
        "extraction-off",
        "The extraction switch is off",
        "Turn on CW_PIPELINE_EXTRACTION_ENABLED for the worker and in .env (make product turns "
        "it on with the fake model), or count the documents waiting instead.",
        "extract-backlog-count",
    ),
    (
        re.compile(r"^error: changed since the question\b"),
        "changed",
        "It changed since you were asked",
        "Ask again: the new question names what runs now. Nothing it did not name was touched.",
        None,
    ),
    (
        re.compile(r"address already in use|port is already allocated|eaddrinuse", re.I),
        "port-in-use",
        "A port it needs is already in use",
        "Stop what is using the port (see Processes), then try again.",
        None,
    ),
    (
        re.compile(r"is not a target of this checkout's makefile|no rule to make target", re.I),
        "no-target",
        "This checkout's Makefile has no such task",
        "Switch to a branch that has it, or update this checkout.",
        None,
    ),
    (
        # only the runner's own lines: "error: refused: ..." and "error: <label> refused: ..."
        re.compile(r"^error: (?:[^:\n]+ )?refused: "),
        "refused",
        "The safety rules refused it",
        "It is never run from this app; the details say why.",
        None,
    ),
    (
        re.compile(r"command not found|cannot run \S+|no such file or directory", re.I),
        "missing-tool",
        "A tool it needs is missing",
        "Check which tools are installed.",
        "doctor",
    ),
)


def classify_failure(lines: Sequence[str], timed_out: bool) -> dict[str, Any]:
    """The error a failed run shows: what went wrong, the fix, and an action that may help."""
    tail = [line for line in lines if line.strip()][-60:]
    detail = "\n".join(tail[-20:])
    if timed_out:
        return {
            "code": "timeout",
            "message": "It took too long and was stopped",
            "detail": detail,
            "fix": "Try again. If it keeps happening, the details show where it waited.",
            "action": None,
        }
    for line in reversed(tail):
        for pattern, code, message, fix, action in _FAILURES:
            if pattern.search(line):
                return {
                    "code": code,
                    "message": message,
                    "detail": detail,
                    "fix": fix,
                    "action": action,
                }
    return {
        "code": "failed",
        "message": "It did not finish",
        "detail": detail,
        "fix": "The details show the last lines it printed.",
        "action": None,
    }


# ---- runs ---------------------------------------------------------------------------------------


@dataclass
class Run:
    run_id: str
    action_id: str
    title: str
    kind: str
    params: dict[str, Any]
    started_at: float
    steps: list[dict[str, Any]]
    state: str = "running"
    finished_at: float | None = None
    current_step: int | None = None
    error: dict[str, Any] | None = None
    lines: collections.deque[dict[str, Any]] = field(
        default_factory=lambda: collections.deque(maxlen=RUN_LINES)
    )
    pending: list[dict[str, Any]] = field(default_factory=list)

    def seconds(self, now: float) -> float:
        return round((self.finished_at or now) - self.started_at, 1)

    def summary(self, now: float) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "action_id": self.action_id,
            "title": self.title,
            "kind": self.kind,
            "params": self.params,
            "state": self.state,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "seconds": self.seconds(now),
            "current_step": self.current_step,
            "steps": [dict(step) for step in self.steps],
            "error": self.error,
        }


class RunManager:
    """The runs of this launch: one step and one read at a time, through the core's runners;
    their events become the stream's run events, output batched every 100 ms."""

    def __init__(
        self,
        backend: Backend,
        hub: Hub,
        wall: Callable[[], float] = time.time,
        on_finished: Callable[[Run], None] | None = None,
    ) -> None:
        self.hub = hub
        self.wall = wall
        self.on_finished = on_finished
        self._lock = threading.RLock()
        self._runs: collections.OrderedDict[str, Run] = collections.OrderedDict()
        self._current: dict[str, Run | None] = {"steps": None, "reads": None}
        self._count = 0
        self.runners: dict[str, RunnerLike] = {
            name: backend.make_runner(name, self._emitter(name)) for name in ("steps", "reads")
        }
        self._stop = threading.Event()
        self._flusher = threading.Thread(target=self._flush_loop, daemon=True, name="run-output")
        self._flusher.start()

    def close(self) -> None:
        self._stop.set()
        for runner in self.runners.values():
            with contextlib.suppress(Exception):
                runner.cancel()

    def current(self, kind: str) -> Run | None:
        with self._lock:
            return self._current["reads" if kind == "read" else "steps"]

    def start(self, spec: catalog.Spec, plan: core.Plan, params: Mapping[str, Any]) -> Run:
        name = "reads" if spec.kind == "read" else "steps"
        runner = self.runners[name]
        with self._lock:
            busy = self._current[name]
            if busy is not None or runner.busy:
                title = busy.title if busy else "Another task"
                raise ApiError(
                    409,
                    "busy",
                    f"{title} is still running.",
                    "One task of this kind runs at a time. Wait for it to finish, or cancel it.",
                    "Wait for it to finish, or press Cancel.",
                )
            self._count += 1
            run = Run(
                run_id=f"r{self._count}",
                action_id=spec.id,
                title=spec.title,
                kind=spec.kind,
                params=dict(params),
                started_at=self.wall(),
                steps=[{"label": s.label, "state": "queued", "seconds": 0} for s in plan.steps],
            )
            self._runs[run.run_id] = run
            while len(self._runs) > RUN_HISTORY:
                oldest = next(iter(self._runs))
                if self._runs[oldest] in self._current.values():
                    break
                self._runs.pop(oldest)
            self._current[name] = run
            if isinstance(runner, Preparable):
                runner.prepare(spec.id)
        if not runner.start(plan):
            with self._lock:
                self._current[name] = None
                run.state = "failed"
                run.finished_at = self.wall()
                lines = [line["text"] for line in run.lines]
            raise ApiError(
                403,
                "refused",
                f"{spec.title} could not start.",
                "\n".join(lines[-10:]),
            )
        return run

    def reset(self, wait: float = 5.0) -> None:
        """Cancels the runs in flight, waits up to ``wait`` seconds for them to end, and forgets
        every run (for ``POST /api/demo/state``)."""
        for runner in self.runners.values():
            runner.cancel()
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            with self._lock:
                if all(run is None for run in self._current.values()):
                    break
            time.sleep(0.02)
        with self._lock:
            self._runs = collections.OrderedDict(
                (run.run_id, run) for run in self._current.values() if run is not None
            )

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(run_id)

    def recent(self, limit: int) -> list[dict[str, Any]]:
        now = self.wall()
        with self._lock:
            runs = list(self._runs.values())[-limit:]
            return [run.summary(now) for run in reversed(runs)]

    def detail(self, run_id: str) -> dict[str, Any] | None:
        now = self.wall()
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            return run.summary(now) | {"lines": list(run.lines)}

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run.state != "running":
                return False
            name = next((n for n, r in self._current.items() if r is run), None)
        if name is None:
            return False
        return self.runners[name].cancel()

    def last(self, action_id: str) -> Run | None:
        with self._lock:
            for run in reversed(self._runs.values()):
                if run.action_id == action_id:
                    return run
        return None

    # the runners' events
    def _emitter(self, name: str) -> Callable[[core.RunnerEvent], None]:
        def emit(event: core.RunnerEvent) -> None:
            try:
                self._on_event(name, event)
            except Exception:  # a defect here must not kill the runner's thread
                log("run event failed:\n" + traceback.format_exc())

        return emit

    def _on_event(self, name: str, event: core.RunnerEvent) -> None:
        with self._lock:
            run = self._current[name]
            if run is None:
                return
            if isinstance(event, core.Line):
                line = {"text": event.text.lstrip("\n"), "tag": event.tag}
                run.lines.append(line)
                run.pending.append(line)
                return
            self._flush(run)
            if isinstance(event, core.Begin):
                self.hub.publish(
                    "run.started",
                    {
                        "run_id": run.run_id,
                        "action_id": run.action_id,
                        "title": run.title,
                        "kind": run.kind,
                        "steps": [step["label"] for step in run.steps],
                        "started_at": run.started_at,
                        "params": run.params,
                    },
                )
            elif isinstance(event, core.StepUpdate):
                if 0 <= event.index < len(run.steps):
                    run.steps[event.index] = {
                        "label": event.label,
                        "state": event.state,
                        "seconds": round(event.seconds, 1),
                    }
                if event.state == "running":
                    run.current_step = event.index
                self.hub.publish(
                    "run.step",
                    {
                        "run_id": run.run_id,
                        "index": event.index,
                        "label": event.label,
                        "state": event.state,
                        "seconds": round(event.seconds, 1),
                    },
                )
            elif isinstance(event, core.End):
                self._finish(name, run, event)

    def _finish(self, name: str, run: Run, event: core.End) -> None:
        run.finished_at = self.wall()
        run.current_step = None
        timed_out = any(result.state == "timeout" for result in event.results)
        if event.cancelled:
            run.state = "cancelled"
        elif event.ok:
            run.state = "ok"
        else:
            run.state = "failed"
            run.error = classify_failure([line["text"] for line in run.lines], timed_out)
            if any(
                result.label == core.COLIMA_STOP_LABEL and result.state == "timeout"
                for result in event.results
            ):
                run.error |= {
                    "message": "Docker did not stop in time",
                    "fix": "colima stop took longer than 2 minutes and was stopped. You can force "
                    "it to stop.",
                    "action": "force-stop-docker",
                }
        self._current[name] = None
        self.hub.publish(
            "run.finished",
            {
                "run_id": run.run_id,
                "action_id": run.action_id,
                "state": run.state,
                "ok": run.state == "ok",
                "cancelled": run.state == "cancelled",
                "seconds": run.seconds(self.wall()),
                "finished_at": run.finished_at,
                "steps": [dict(step) for step in run.steps],
                "error": run.error,
            },
        )
        if self.on_finished is not None:
            self.on_finished(run)

    def _flush(self, run: Run) -> None:
        while run.pending:
            batch, run.pending = run.pending[:OUTPUT_BATCH], run.pending[OUTPUT_BATCH:]
            self.hub.publish("run.output", {"run_id": run.run_id, "lines": batch})

    def _flush_loop(self) -> None:
        while not self._stop.wait(OUTPUT_EVERY):
            with self._lock:
                for run in self._current.values():
                    if run is not None:
                        self._flush(run)


# ---- the app: every route's logic, apart from HTTP ---------------------------------------------


class Lifetime:
    def __init__(self, clock: Callable[[], float], idle_seconds: float) -> None:
        self.clock = clock
        self.idle_seconds = idle_seconds
        self.last = clock()

    def touch(self) -> None:
        self.last = self.clock()

    def idle_for(self) -> float:
        return self.clock() - self.last

    def expired(self) -> bool:
        return self.idle_for() > self.idle_seconds


class App:
    """The helper's state and every route's logic. The HTTP handler only checks the request and
    turns these answers into responses."""

    def __init__(
        self,
        backend: Backend,
        *,
        token: str,
        port: int,
        prefs: Prefs,
        ui_dir: Path = UI_DIR,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        idle_seconds: float = IDLE_EXIT_SECONDS,
    ) -> None:
        self.backend = backend
        self.token = token
        self.port = port
        self.prefs = prefs
        self.ui_dir = ui_dir.resolve()
        self.clock = clock
        self.wall = wall
        self.started_at = wall()
        self.host_header = f"127.0.0.1:{port}"
        self.origin = f"http://127.0.0.1:{port}"
        self.hub = Hub()
        self.lifetime = Lifetime(clock, idle_seconds)
        self.confirms = Book("c-", CONFIRM_SECONDS, clock)
        self.tickets = Book("t-", TICKET_SECONDS, clock)
        self.launches = Book("l-", LAUNCH_SECONDS, clock)
        self.catalog = catalog.Catalog.load(backend.project)
        self.flights = core.SingleFlight()
        self._lock = threading.RLock()
        self.status: core.Status | None = None
        self.snapshot: core.ProcessSnapshot | None = None
        self.git: core.GitState | None = None
        self._status_body: dict[str, Any] | None = None
        self._catalog_fingerprint: tuple[Any, ...] = ()
        self.kafka_snapshot: core.KafkaSnapshot | None = None
        self.kafka_limit = core.RateLimit(core.KAFKA_MIN_SECONDS, clock)
        self._cached: dict[str, tuple[float, Any]] = {}
        self.runs = RunManager(backend, self.hub, wall, self._run_finished)
        self.poller = Poller(self)

    # the context the catalog builds with
    @property
    def project(self) -> core.Project:
        return self.backend.project

    @property
    def plans(self) -> core.Plans:
        return self.backend.plans

    def backups(self) -> list[core.Dump]:
        return self.backend.backups()

    def compose_services(self) -> list[str]:
        return self.backend.compose_services()

    def doc_choices(self) -> list[tuple[str, str]]:
        return [(str(doc["id"]), str(doc["label"])) for doc in self.backend.docs()]

    # probes landing
    def on_probe(self, kind: str, result: Any) -> None:
        with self._lock:
            if kind == "status":
                self.status = result
            elif kind == "processes":
                self.snapshot = result
            elif kind == "git":
                self.git = result
            body = status_view(
                self.project, self.status, self.snapshot, self.git, demo=self.backend.demo
            )
            compare = {k: v for k, v in body.items() if k != "taken_at"}
            previous = self._status_body
            changed = previous is None or compare != {
                k: v for k, v in previous.items() if k != "taken_at"
            }
            self._status_body = body
            fingerprint = self._catalog_fingerprint_now()
            catalog_changed = fingerprint != self._catalog_fingerprint
            self._catalog_fingerprint = fingerprint
        if changed:
            self.hub.publish("status", body)
        if kind == "processes":
            self.hub.publish("processes", {"taken_at": result.taken_at})
        if catalog_changed:
            self.hub.publish("actions", {})

    def _catalog_fingerprint_now(self) -> tuple[Any, ...]:
        status = self.status
        return (
            status.docker if status else None,
            bool(status.up.get("product.internal")) if status else None,
            tuple(dump.path for dump in self.backend.backups()),
            self.backend.env_file_exists(),
        )

    def _run_finished(self, run: Run) -> None:
        title = run.title
        toast: dict[str, Any]
        if run.state == "ok":
            toast = {"level": "success", "title": f"{title}: done", "body": "", "action": None}
        elif run.state == "cancelled":
            toast = {"level": "info", "title": f"{title} was cancelled", "body": "", "action": None}
        else:
            error = run.error or {}
            toast = {
                "level": "error",
                "title": f"{title} did not finish",
                "body": f"{error.get('message', '')}. {error.get('fix', '')}".strip(". "),
                "action": error.get("action"),
            }
        # one notice per run: a colima stop that timed out says so through run.error, whose
        # action is force-stop-docker
        self.hub.publish("toast", toast | {"run_id": run.run_id})
        self.poller.poke("status", "processes")
        self.hub.publish("actions", {})

    # reads
    def meta(self) -> dict[str, Any]:
        return {
            "api": API_VERSION,
            "demo": self.backend.demo,
            "build": self.backend.build,
            "repo": str(self.project.repo),
            "started_at": self.started_at,
        }

    def hello(self, resync: bool) -> dict[str, Any]:
        return {
            "api": API_VERSION,
            "demo": self.backend.demo,
            "build": self.backend.build,
            "resync": resync,
        }

    def status_body(self) -> dict[str, Any]:
        with self._lock:
            if self._status_body is None:
                self._status_body = status_view(
                    self.project, self.status, self.snapshot, self.git, demo=self.backend.demo
                )
            return self._status_body

    def actions(self) -> dict[str, Any]:
        entries = [self.entry(spec) for spec in self.catalog.specs.values()]
        return {
            "groups": [{"id": key, "title": title} for key, title in catalog.GROUPS],
            "actions": entries,
        }

    def availability(self, spec: catalog.Spec) -> tuple[bool, str, str | None]:
        if spec.safety == "refused":
            return False, spec.refused, spec.covered_by or None
        status = self.status
        if status is not None:
            if "docker" in spec.needs and not status.docker and spec.id != "docker-start":
                return False, "Docker is not running.", "docker-start"
            if "product" in spec.needs and not status.up.get("product.internal"):
                return False, "The product is not running.", "product-start"
        for param in spec.params:
            if param.required and param.default is None and not catalog.choices(self, param):
                if param.source == "backups":
                    return False, "There is no backup yet.", "backup"
                return False, f"There is nothing to choose for {param.label} here.", None
        if spec.id == "open-env" and not self.backend.env_file_exists():
            return (
                False,
                "There is no .env file yet. Starting the databases once creates it.",
                "databases-start",
            )
        return True, "", None

    def entry(self, spec: catalog.Spec) -> dict[str, Any]:
        enabled, reason, fix = self.availability(spec)
        steps: list[str] = []
        command = ""
        if spec.safety != "refused" and spec.kind != "open":
            with contextlib.suppress(catalog.ParamError, KeyError, StopIteration):
                values = {
                    p.name: p.default
                    if p.default is not None
                    else next(iter(catalog.choices(self, p)), ("", ""))[0]
                    for p in spec.params
                }
                built = catalog.build(self, spec, values)
                if built.plan is not None:
                    steps, command = plan_outline(built.plan)
        if spec.source == "make":
            command = command or f"make {spec.target}"
        return {
            "id": spec.id,
            "title": spec.title,
            "summary": spec.summary,
            "what_happens": list(spec.what_happens),
            "duration": spec.duration,
            "group": spec.group,
            "safety": spec.safety,
            "needs_confirm": spec.needs_confirm,
            "confirm": spec.confirm or None,
            "enabled": enabled,
            "reason": reason,
            "fix_action": fix,
            "kind": spec.kind,
            "button": spec.button,
            "params": [self.param_view(param) for param in spec.params],
            "steps": steps,
            "command": command,
            "url": spec.url or None,
            "source": spec.source,
            "covered_by": spec.covered_by or None,
            "preview": spec.needs_confirm,
            "calls_model": spec.calls_model,
            "keywords": keywords(spec),
        }

    def param_view(self, param: catalog.Param) -> dict[str, Any]:
        return {
            "name": param.name,
            "label": param.label,
            "kind": param.kind,
            "choices": [
                {"value": value, "label": label} for value, label in catalog.choices(self, param)
            ],
            "default": param.default,
            "required": param.required,
            "help": param.help,
        }

    def spec(self, action_id: str) -> catalog.Spec:
        spec = self.catalog.get(action_id)
        if spec is None:
            raise ApiError(404, "not-found", "There is no such action.", action_id)
        return spec

    def check_runnable(self, spec: catalog.Spec, body: Mapping[str, Any]) -> dict[str, Any]:
        """The checks every preview and run passes: not refused, enabled now, and parameters
        that are the action's and among its choices. Returns the checked parameters."""
        if spec.safety == "refused":
            raise ApiError(
                403,
                "refused",
                f"{spec.title} is never run from this app.",
                spec.refused,
                "",
                spec.covered_by or None,
            )
        enabled, reason, fix = self.availability(spec)
        if not enabled:
            raise ApiError(403, "disabled", reason, "", "", fix)
        raw = body.get("params", {})
        if not isinstance(raw, dict):
            raise ApiError(400, "bad-params", "The parameters must be an object.")
        try:
            return catalog.normalise(self, spec, raw)
        except catalog.ParamError as exc:
            raise ApiError(400, "bad-params", str(exc)) from exc

    def warnings(self, spec: catalog.Spec) -> list[dict[str, Any]]:
        """What the confirm warns about, each with a plain ``message``, a ``title``, a ``tone``
        (danger, warning or info) and, for other sessions, the ``items`` it names: the branch
        when the action changes something, other sessions the action breaks, what it needs that
        is not running, and files it rewrites."""
        warnings: list[dict[str, Any]] = []
        git = self.git
        changes = spec.migrates or spec.safety in ("changes-data", "destructive")
        if changes and git is not None and not git.error and git.branch and not git.on_main:
            text = f"This checkout is on {git.branch}, not main."
            if spec.migrates:
                text += (
                    " This applies that branch's database changes to the shared development "
                    "database. Other branches and sessions use the same database, and may fail "
                    "until it is migrated back or reset."
                )
            else:
                text += " What this runs is that branch's code."
            warnings.append(
                {
                    "code": "not-main",
                    "tone": "danger" if spec.migrates else "warning",
                    "title": f"This checkout is on {git.branch}, not main",
                    "message": text,
                    "items": [],
                }
            )
        takes = set(spec.takes)
        if spec.migrates or spec.safety == "destructive":
            takes.add("docker")
        sessions = sessions_view(self.snapshot, self.project.repo)
        for use, title, verb in (
            (
                "docker",
                "Other sessions are using Docker's databases and queues",
                "Changing the database under them may break them."
                if spec.migrates and "docker" not in spec.takes
                else "Stopping Docker or replacing its data will break them.",
            ),
            (
                "product",
                "Other sessions are using the product",
                "Stopping the product will break them.",
            ),
        ):
            hit = [s for s in sessions if use in s["uses"] and use in takes]
            if hit and not any(w["code"] == "sessions" for w in warnings):
                first = hit[0]
                warnings.append(
                    {
                        "code": "sessions",
                        "tone": "danger",
                        "title": title,
                        "message": f"{KIND_WORDS[first['kind']]} is running {first['text']} in "
                        f"this checkout. {verb}",
                        "items": [f"{KIND_WORDS[s['kind']]}: {s['text']}" for s in hit],
                    }
                )
        status = self.status
        if status is not None:
            if "docker" in spec.needs and not status.docker:
                warnings.append(
                    {
                        "code": "docker-down",
                        "tone": "warning",
                        "title": "Docker is not running",
                        "message": "Docker is not running. Start Docker first.",
                        "items": [],
                    }
                )
            if "product" in spec.needs and not status.up.get("product.internal"):
                warnings.append(
                    {
                        "code": "product-down",
                        "tone": "warning",
                        "title": "The product is not running",
                        "message": "The product is not running. Start the product first.",
                        "items": [],
                    }
                )
        provider = status.llm_provider if status is not None else None
        if spec.calls_model and not provider:
            warnings.append(
                {
                    "code": "provider",
                    "tone": "warning",
                    "title": "This may call a paid model",
                    "message": "This app cannot tell which model the gateway uses: the product "
                    "is not running, or its log does not say. If the gateway is set up with a "
                    "paid provider (CW_LLM_PROVIDER), each document is a paid call: up to 1,000 "
                    "in this run.",
                    "items": [],
                }
            )
        elif spec.calls_model and provider:
            if provider == "fake":
                warnings.append(
                    {
                        "code": "provider",
                        "tone": "info",
                        "title": "The product's gateway answers from its fake model",
                        "message": "Each document goes to the gateway's fake model "
                        "(CW_LLM_PROVIDER=fake): it costs nothing, and what it extracts is made "
                        "up.",
                        "items": [],
                    }
                )
            else:
                warnings.append(
                    {
                        "code": "provider",
                        "tone": "warning",
                        "title": f"The product's gateway uses {provider}, a paid model",
                        "message": f"Each document is a model call through {provider} "
                        f"(CW_LLM_PROVIDER={provider}), and each call is paid: up to 1,000 in "
                        "this run.",
                        "items": [],
                    }
                )
        if spec.rewrites and git is not None and git.dirty:
            files = "file" if git.dirty == 1 else "files"
            warnings.append(
                {
                    "code": "dirty",
                    "tone": "info",
                    "title": f"{git.dirty} uncommitted {files}",
                    "message": f"This checkout has {git.dirty} uncommitted {files}. This rewrites "
                    "files in it; they show up as changed.",
                    "items": [],
                }
            )
        return warnings

    def reaches(self, pids: Sequence[int]) -> list[dict[str, Any]]:
        """The processes a stop's confirm names: pid, command and who started it."""
        snapshot = self.snapshot
        if snapshot is None:
            return []
        repo = self.project.repo
        return [
            {
                "pid": pid,
                "command": core.short_command(snapshot.procs[pid].command, repo, 90)
                if pid in snapshot.procs
                else "",
                "origin": snapshot.origins.get(pid, ""),
            }
            for pid in pids
        ]

    def web_pids(self) -> tuple[dict[int, str], list[str]]:
        """The pids the web app's stop would reach now, each with its program, and the lines
        naming them, from the snapshot of the question (:meth:`fresh_processes`)."""
        snapshot = self.snapshot
        if snapshot is None:
            return {}, []
        targets, notes = core.web_stop_targets(self.project, snapshot)
        pids = {
            pid: snapshot.procs[pid].command
            for target in targets
            for pid in target.pids
            if pid in snapshot.procs
        }
        lines = [core.describe_stop(target, snapshot, self.project.repo) for target in targets]
        return pids, [*lines, *notes]

    def fresh_processes(self) -> core.ProcessSnapshot:
        """A new process scan for a question about processes (a stop's, a warning naming other
        sessions), never the poller's older one; bounded by :data:`QUESTION_SCAN_SECONDS`."""
        future = _QUESTION_POOL.submit(self.backend.probe_processes)
        try:
            snapshot = future.result(timeout=QUESTION_SCAN_SECONDS)
        except FuturesTimeout as exc:
            raise ApiError(
                503,
                "scan-slow",
                "The processes could not be read in time",
                f"ps and lsof did not answer within {QUESTION_SCAN_SECONDS:.0f} s.",
                "Try again in a moment.",
            ) from exc
        except Exception as exc:
            raise ApiError(
                503,
                "scan-failed",
                "The processes could not be read",
                str(exc),
                "Try again in a moment.",
            ) from exc
        self.on_probe("processes", snapshot)
        return snapshot

    def preview(self, action_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        spec = self.spec(action_id)
        params = self.check_runnable(spec, body)
        extra: dict[str, Any] = {}
        details: list[str] = []
        reaches: list[dict[str, Any]] = []
        if spec.needs_confirm:
            self.fresh_processes()  # what it reaches and the sessions it warns about, as of now
        if spec.id in ("stop-everything", "web-stop"):
            pids, details = self.web_pids()
            extra["pids"] = pids
            reaches = self.reaches(list(pids))
        try:
            built = catalog.build(self, spec, params, expected=extra.get("pids"))
        except catalog.ParamError as exc:
            raise ApiError(400, "bad-params", str(exc)) from exc
        steps, command = plan_outline(built.plan) if built.plan else ([], "")
        if built.plan is not None and built.plan.confirm:
            details.insert(0, built.plan.confirm)
        if not spec.needs_confirm:
            return {
                "action_id": spec.id,
                "params": params,
                "confirm": None,
                "confirm_token": None,
                "expires_in": 0,
                "steps": steps,
                "command": command,
            }
        token = self.confirms.issue(confirm_key(spec.id, params), extra)
        return {
            "action_id": spec.id,
            "params": params,
            "confirm": {
                "title": f"{spec.title}?",
                "text": spec.confirm or spec.summary,
                "what_happens": list(spec.what_happens),
                "warnings": self.warnings(spec),
                "button": spec.title,
                "details": "\n\n".join(details),
                "reaches": reaches,
            },
            "reaches": reaches,
            "confirm_token": token,
            "expires_in": int(CONFIRM_SECONDS),
            "steps": steps,
            "command": command,
        }

    def run(self, action_id: str, body: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
        spec = self.spec(action_id)
        params = self.check_runnable(spec, body)
        extra: dict[str, Any] = {}
        if spec.needs_confirm:
            token = body.get("confirm_token") or body.get("confirm")
            taken = self.confirms.take(token, confirm_key(spec.id, params))
            if taken is None:
                raise ApiError(
                    428,
                    "confirm-required",
                    "Please confirm first.",
                    "Ask for a preview, show its confirm, and send its confirm_token back within "
                    "two minutes. A token works once, for the same parameters.",
                    "Press the button again to see what will happen.",
                )
            extra = taken
        try:
            built = catalog.build(self, spec, params, expected=extra.get("pids"))
        except catalog.ParamError as exc:
            raise ApiError(400, "bad-params", str(exc)) from exc
        if built.open_path is not None or built.psql:
            return 200, self._open(built)
        plan = built.plan
        if plan is None:
            raise ApiError(400, "bad-params", f"{spec.title} has nothing to run.")
        if problems := core.plan_problems(plan, self.project.known_targets):
            raise ApiError(
                403,
                "refused",
                f"The safety rules refuse {spec.title}.",
                "\n".join(problems),
            )
        run = self.runs.start(spec, plan, params)
        return 202, {"run_id": run.run_id}

    def _open(self, built: catalog.Built) -> dict[str, Any]:
        try:
            if built.psql:
                target = self.backend.open_psql()
            else:
                assert built.open_path is not None
                self.backend.open_path(built.open_path, built.text_editor)
                target = str(built.open_path)
        except FileNotFoundError as exc:
            missing = built.open_path or Path(str(exc))
            raise ApiError(
                404, "not-found", f"{missing.name} does not exist yet.", str(missing)
            ) from exc
        except core.RefusedError as exc:
            raise ApiError(403, "refused", "The safety rules refuse to open it.", str(exc)) from exc
        except OSError as exc:
            raise ApiError(500, "internal", "It could not be opened.", str(exc)) from exc
        name = Path(target).name or target
        return {"ok": True, "opened": True, "target": target, "message": f"Opened {name}"}

    def cancel(self, run_id: str) -> dict[str, Any]:
        if self.runs.get(run_id) is None:
            raise ApiError(404, "not-found", "There is no such run.", run_id)
        if not self.runs.cancel(run_id):
            raise ApiError(409, "not-running", "That run has already finished.")
        return {"ok": True}

    # processes
    def processes(self) -> dict[str, Any]:
        snapshot = self.snapshot
        if snapshot is None:
            self.poller.poke("processes")
            return {"taken_at": None, "ports": [], "processes": [], "error": "", "loading": True}
        return processes_view(self.project, snapshot)

    def stop_preview(self, pid: int) -> dict[str, Any]:
        snapshot = self.fresh_processes()
        if pid not in snapshot.procs:
            raise ApiError(404, "not-found", f"Process {pid} is not running.")
        repo = self.project.repo
        options = core.stop_options(pid, snapshot)
        views = []
        for option in options:
            views.append(
                {
                    "mode": option.mode,
                    "pgid": option.pgid,
                    "text": core.describe_stop(option, snapshot, repo),
                    "pids": [
                        {
                            "pid": p,
                            "command": core.short_command(snapshot.procs[p].command, repo, 90)
                            if p in snapshot.procs
                            else "",
                            "origin": snapshot.origins.get(p, ""),
                        }
                        for p in option.pids
                    ],
                    "refused": option.refused,
                }
            )
        # the token carries each mode's pids with the program each runs now: the stop signals
        # only those, and only while they still run it
        allowed = {
            o.mode: [[p, snapshot.procs[p].command] for p in o.pids if p in snapshot.procs]
            for o in options
            if not o.refused and o.pids
        }
        warnings = []
        pids = {p for o in options for p in o.pids}
        if not all(snapshot.origins.get(p, "").startswith("this panel") for p in pids):
            foreign = sorted(p for p in pids if not snapshot.origins.get(p, "").startswith("this"))
            warnings.append(
                {
                    "code": "sessions",
                    "tone": "warning",
                    "title": "This app did not start all of these",
                    "message": "This app did not start every one of these. Another session may "
                    "be using them, for example a make check in a terminal or Claude's build "
                    "agent.",
                    "items": [
                        f"{p}: {core.short_command(snapshot.procs[p].command, repo, 70)}"
                        for p in foreign
                        if p in snapshot.procs
                    ],
                }
            )
        token = None
        if allowed:
            token = self.confirms.issue(
                f"stop:{pid}",
                {"modes": allowed, "command": snapshot.procs[pid].command},
            )
        return {
            "pid": pid,
            "command": core.short_command(snapshot.procs[pid].command, repo, 110),
            "options": views,
            "warnings": warnings,
            "confirm_token": token,
            "expires_in": int(CONFIRM_SECONDS),
        }

    def stop_process(self, pid: int, body: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
        mode = body.get("mode")
        if mode not in ("group", "tree"):
            raise ApiError(400, "bad-params", 'mode must be "group" or "tree".')
        taken = self.confirms.take(body.get("confirm_token"), f"stop:{pid}")
        if taken is None or mode not in taken.get("modes", {}):
            raise ApiError(
                428,
                "confirm-required",
                "Please confirm first.",
                "Ask for the stop preview, then send its confirm_token with one of its modes.",
                "Press Stop again to see what it reaches.",
            )
        named = {int(p): str(command) for p, command in taken["modes"][mode]}
        plan = self.plans.stop_process(
            pid, str(taken["command"]), "tree" if mode == "tree" else "group", named
        )
        spec = catalog.Spec(
            id=f"process-stop:{pid}",
            title=f"Stop process {pid}",
            summary="",
            what_happens=(),
            duration="a few seconds",
            group="tools",
            safety="stops-things",
        )
        if problems := core.plan_problems(plan, self.project.known_targets):
            raise ApiError(
                403, "refused", "The safety rules refuse this stop.", "\n".join(problems)
            )
        run = self.runs.start(spec, plan, {"pid": pid, "mode": mode})
        return 202, {"run_id": run.run_id}

    # cached reads that probe in the background
    def _cached_read(
        self, key: str, max_age: float, work: Callable[[], Any], event: str
    ) -> tuple[Any, bool]:
        """The last result of ``work`` and whether it is being read again: a read older than
        ``max_age`` starts in the background (one at a time), and an event tells the stream
        when it lands. The very first read is waited for, up to ``FIRST_READ_SECONDS``, so a
        window that opens gets the answer at once when it is quick."""
        now = self.clock()
        cached = self._cached.get(key)
        stale = cached is None or now - cached[0] > max_age
        reading = False
        if stale and self.flights.begin(key):
            reading = True
            landed = threading.Event()

            def go() -> None:
                try:
                    result = work()
                    self._cached[key] = (self.clock(), result)
                    self.hub.publish(event, {})
                except Exception:
                    log(f"{key} read failed:\n" + traceback.format_exc())
                finally:
                    self.flights.end(key)
                    landed.set()

            threading.Thread(target=go, daemon=True, name=f"read-{key}").start()
            if cached is None and landed.wait(FIRST_READ_SECONDS):
                cached = self._cached.get(key)
                reading = False
        elif key in self.flights.running():
            reading = True
        return (cached[1] if cached else None), reading

    def features(self) -> dict[str, Any]:
        def work() -> list[dict[str, Any]]:
            last = self.runs.last("product-check")
            check = last.summary(self.wall()) if last else None
            return self.backend.features(self.status, check)

        features, reading = self._cached_read("features", CACHE_SECONDS, work, "features")
        return {"features": features or [], "loading": features is None, "reading": reading}

    def github(self) -> dict[str, Any]:
        info, reading = self._cached_read(
            "github", GITHUB_SECONDS, lambda: self.backend.github(self.git), "github"
        )
        if info is None:
            return {
                "available": False,
                "reason": "Reading GitHub…",
                "links": [],
                "prs": [],
                "loading": True,
            }
        return dict(info) | {"loading": False, "reading": reading}

    def flags(self) -> dict[str, Any]:
        rows, error = self.backend.flags()
        return {"flags": [dataclasses.asdict(row) for row in rows], "error": error}

    def kafka(self) -> dict[str, Any]:
        return kafka_view(
            self.kafka_snapshot, self.kafka_limit.remaining(), "kafka" in self.flights.running()
        )

    def kafka_refresh(self) -> dict[str, Any]:
        wait = self.kafka_limit.wait()
        if wait > 0 or not self.flights.begin("kafka"):
            return {"started": False, "next_in": max(round(wait), 0)}

        def go() -> None:
            try:
                self.kafka_snapshot = self.backend.probe_kafka()
            except Exception:
                log("kafka read failed:\n" + traceback.format_exc())
            finally:
                self.flights.end("kafka")
                self.hub.publish("kafka", self.kafka())

        threading.Thread(target=go, daemon=True, name="read-kafka").start()
        return {"started": True, "next_in": int(core.KAFKA_MIN_SECONDS)}

    def log_sources(self) -> dict[str, Any]:
        return {"sources": self.backend.log_sources()}

    def read_log(self, source: str, tail: int) -> dict[str, Any]:
        known = {item["id"] for item in self.backend.log_sources()}
        if source not in known:
            raise ApiError(404, "not-found", "There is no such log.", source)
        return self.backend.read_log(source, max(1, min(tail, RUN_LINES)))

    def docs(self) -> dict[str, Any]:
        return {"docs": self.backend.docs()}

    def open_doc(self, doc_id: str) -> dict[str, Any]:
        doc = next((d for d in self.backend.docs() if d["id"] == doc_id), None)
        if doc is None:
            raise ApiError(404, "not-found", "There is no such document.", doc_id)
        path = self.project.repo / str(doc["path"])
        try:
            self.backend.open_path(path, False)
        except FileNotFoundError as exc:
            raise ApiError(404, "not-found", f"{path.name} does not exist.", str(path)) from exc
        except (core.RefusedError, OSError) as exc:
            raise ApiError(500, "internal", "It could not be opened.", str(exc)) from exc
        return {
            "ok": True,
            "opened": True,
            "target": str(path),
            "message": f"Opened {doc['label']}",
        }

    def heartbeat(self) -> dict[str, Any]:
        return {"ok": True, "idle_exit_in": int(self.lifetime.idle_seconds)}

    def save_prefs(self, body: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return self.prefs.update(body)
        except ValueError as exc:
            raise ApiError(400, "bad-params", str(exc)) from exc
        except OSError as exc:
            raise ApiError(
                500, "internal", "The preferences could not be saved.", str(exc)
            ) from exc

    def launch_url(self, view: str = "") -> str:
        """An address that opens the window: a single-use launch code in its fragment, which the
        page swaps for the token (``POST /api/launch``). No token ever travels in a URL."""
        url = f"{self.origin}/#launch={self.launches.issue()}"
        return url + (f"&view={view}" if view else "")

    def launch(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """``POST /api/launch``: the token, once, for a live launch code (the code is burned)."""
        if self.launches.take(body.get("code")) is None:
            raise ApiError(
                401,
                "launch-expired",
                "This window's link has been used or has expired.",
                f"A launch code works once, within {LAUNCH_SECONDS:.0f} seconds.",
                "Open the app again.",
            )
        return {"token": self.token}

    def demo_state(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """``POST /api/demo/state``, for the UI tests: only with ``--demo``. The whole body is
        checked before anything changes; the stream then sees the new world at once."""
        backend = self.backend
        if not backend.demo or not isinstance(backend, DemoControl):
            raise ApiError(404, "not-found", "There is no such address.")
        aliases = {"failNext": "fail_next", "expireTokens": "expire_tokens"}
        given = {aliases.get(key, key): value for key, value in body.items()}
        known = {"reset", "world", "fail_next", "prefs", "speed", "expire_tokens"}
        if unknown := sorted(set(given) - known):
            raise ApiError(400, "bad-params", f"Unknown keys: {', '.join(unknown)}.")
        for key in ("reset", "expire_tokens"):
            if not isinstance(given.get(key, False), bool):
                raise ApiError(400, "bad-params", f"{key} must be true or false.")
        try:
            change = backend.parse_state(given, self.catalog.specs.keys())
            prefs = given.get("prefs")
            if prefs is not None and not isinstance(prefs, dict):
                raise catalog.ParamError("prefs must be an object")
            checked_prefs = validate_prefs(prefs) if prefs else {}
        except (catalog.ParamError, ValueError) as exc:
            raise ApiError(400, "bad-params", str(exc)) from exc
        if given.get("reset"):
            self.runs.reset()
            backend.reset_world()
            self.confirms.clear()
            self.kafka_snapshot = None
            self.kafka_limit = core.RateLimit(core.KAFKA_MIN_SECONDS, self.clock)
        if given.get("expire_tokens"):
            self.confirms.clear()
        backend.apply_state(change)
        if checked_prefs:
            self.prefs.update(checked_prefs)
        self._cached.clear()
        with self._lock:  # all three first, so the stream gets one status of the whole world
            self.status = backend.probe_status()
            self.git = backend.probe_git()
        self.on_probe("processes", backend.probe_processes())
        self.hub.publish("actions", {})
        return {"ok": True, "world": backend.describe_world(), "prefs": self.prefs.get()}

    def shutdown(self) -> None:
        self.poller.stop()
        self.runs.close()
        self.hub.close_all()


def keywords(spec: catalog.Spec) -> str:
    """Words the command palette also matches: the make target, the id's words, the group."""
    words = {spec.target, *spec.id.replace(":", "-").split("-"), spec.group}
    if spec.source == "make":
        words.add("make")
    return " ".join(sorted(word for word in words if word))


def plan_outline(plan: core.Plan) -> tuple[list[str], str]:
    """A plan's step labels, and the programs it runs, one per line, for "Show details"."""
    programs = []
    for step in plan.steps:
        if isinstance(step, core.Cmd):
            programs.append(" ".join(step.argv))
        else:
            main = [argv for argv in step.commands if argv not in core.scan_commands()]
            main = [argv for argv in main if argv not in (core.DOCKER_INFO, core.PS_ARGV)]
            programs.extend(" ".join(argv) for argv in main)
    return [step.label for step in plan.steps], "\n".join(programs)


# ---- the shared poller -------------------------------------------------------------------------

SCHEDULE: Final[Mapping[str, tuple[float, float]]] = {
    "status": (2.0, 15.0),
    "processes": (10.0, 30.0),
    "git": (30.0, 60.0),
}


class Poller:
    """One background loop for the whole helper: each probe on its own thread, one of each kind
    at a time, every 2 s (status) while a window is connected and every 15 s otherwise."""

    def __init__(self, app: App) -> None:
        self.app = app
        self._flights = core.SingleFlight()
        self._due = dict.fromkeys(SCHEDULE, 0.0)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="poller")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def poke(self, *kinds: str) -> None:
        for kind in kinds:
            self._due[kind] = 0.0

    def connected(self) -> bool:
        return self.app.hub.count() > 0 or self.app.lifetime.idle_for() < 30

    def _loop(self) -> None:
        while not self._stop.wait(0.25):
            now = self.app.clock()
            connected = self.connected()
            for kind, (fast, slow) in SCHEDULE.items():
                if now < self._due[kind] or not self._flights.begin(kind):
                    continue
                self._due[kind] = now + (fast if connected else slow)
                threading.Thread(target=self._probe, args=(kind,), daemon=True).start()

    def _probe(self, kind: str) -> None:
        backend = self.app.backend
        try:
            if kind == "status":
                result: Any = backend.probe_status()
            elif kind == "processes":
                result = backend.probe_processes()
            else:
                result = backend.probe_git()
            self.app.on_probe(kind, result)
        except Exception:  # a probe's defect must not stop the polling
            log(f"the {kind} probe failed:\n" + traceback.format_exc())
        finally:
            self._flights.end(kind)


# ---- the real core -----------------------------------------------------------------------------


FEATURE_ADMIN: Final[Mapping[str, tuple[str, ...]]] = {
    "review-queue": ("admin.review", "admin.review.stats"),
    "pipeline-tasks": ("admin.pipeline.tasks", "admin.pipeline", "admin.sources"),
    "fan-out": ("admin.fan-outs",),
    "changes": ("admin.impact", "admin.rulebook.versions"),
    "notifications": ("admin.notifications",),
    "flags": ("admin.flags",),
    "runs": ("admin.decisions",),
}


def tail_file(path: Path, count: int, limit: int = 512 * 1024) -> tuple[list[str], bool]:
    """The last ``count`` lines of a file, read from at most its last ``limit`` bytes, cleaned of
    colour codes; and whether there was more."""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(size - limit, 0))
        text = handle.read().decode("utf-8", errors="replace")
    lines = [core.clean_line(line) for line in text.splitlines()]
    if size > limit and lines:
        lines = lines[1:]
    return lines[-count:], len(lines) > count or size > limit


def openapi_routes(repo: Path) -> set[str]:
    """Every ``GET`` route of the committed OpenAPI specs."""
    routes: set[str] = set()
    for spec in sorted((repo / "packages" / "contracts" / "openapi").glob("*.v1.json")):
        with contextlib.suppress(OSError, ValueError):
            paths = json.loads(spec.read_text(encoding="utf-8")).get("paths", {})
            routes.update(path for path, ops in paths.items() if "get" in ops)
    return routes


class RealBackend:
    """The checkout itself, through panel_core: real probes, real plans, the checked runner."""

    demo = False

    def __init__(self, repo: Path | None = None) -> None:
        self._project = core.Project.load(repo)
        project = self._project
        self.registry = core.Registry(project.panel_dir)
        self.manager = core.BackgroundManager(
            project.repo, project.env, self.registry, project.known_targets
        )
        self._plans = core.Plans(project, self.manager)
        self.build = core.describe_build(core.read_build(HERE))
        self.routes = openapi_routes(project.repo)
        self._remote: str | None = None

    @property
    def project(self) -> core.Project:
        return self._project

    @property
    def plans(self) -> core.Plans:
        return self._plans

    def probe_status(self) -> core.Status:
        return core.probe_status(self.project, self.manager)

    def probe_processes(self) -> core.ProcessSnapshot:
        return core.probe_processes(self.project.repo, self.project.env, self.registry)

    def probe_git(self) -> core.GitState:
        return core.probe_git(self.project.repo, self.project.env)

    def probe_kafka(self) -> core.KafkaSnapshot:
        return core.probe_kafka(self.project.repo, self.project.env)

    def flags(self) -> tuple[list[core.FlagRow], str]:
        return core.load_flags(self.project.repo)

    def backups(self) -> list[core.Dump]:
        return core.list_backups(self.project.repo)

    def compose_services(self) -> list[str]:
        return [service.name for service in core.COMPOSE_SERVICES]

    def env_file_exists(self) -> bool:
        return (self.project.repo / ".env").is_file()

    def make_runner(self, name: str, emit: Callable[[core.RunnerEvent], None]) -> RunnerLike:
        project = self.project
        timeout = 180.0 if name == "reads" else None
        return core.Runner(
            name, project.repo, project.env, emit, self.registry, timeout, project.known_targets
        )

    def open_path(self, path: Path, text_editor: bool) -> None:
        if not path.exists():
            raise FileNotFoundError(str(path))
        core.open_path(path, self.project.env, text_editor=text_editor)

    def open_psql(self) -> str:
        return str(core.open_psql_terminal(self.project.repo, self.project.env))

    def docs(self) -> list[dict[str, Any]]:
        repo = self.project.repo
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
            if (repo / path).exists()
        ]

    def log_sources(self) -> list[dict[str, Any]]:
        project = self.project
        sources: list[dict[str, Any]] = []

        def add(source_id: str, label: str, group: str, path: Path) -> None:
            sources.append(
                {
                    "id": source_id,
                    "label": label,
                    "group": group,
                    "path": str(path.relative_to(project.repo)),
                    "kind": "file",
                    "available": path.is_file(),
                }
            )

        add("web", "Web app", "Services", project.web_stack_dir / "web.log")
        for name in core.SERVICES:
            add(
                f"service:{name}",
                f"{name} service",
                "Services",
                project.web_stack_dir / f"{name}.log",
            )
        for proc in ("app", "worker", "web"):
            add(
                f"product:{proc}", f"Product {proc}", "Product", project.product_dir / f"{proc}.log"
            )
        for spec in project.backgrounds()[1:]:
            add(f"panel:{spec.key}", spec.label, "Workers and relays", spec.log_file)
        for service in core.COMPOSE_SERVICES:
            sources.append(
                {
                    "id": f"container:{service.name}",
                    "label": service.what,
                    "group": "Containers",
                    "path": "",
                    "kind": "container",
                    "available": True,
                }
            )
        return sources

    def read_log(self, source: str, tail: int) -> dict[str, Any]:
        item = next(s for s in self.log_sources() if s["id"] == source)
        base = {"id": source, "label": item["label"], "path": item["path"], "taken_at": time.time()}
        if item["kind"] == "container":
            name = source.split(":", 1)[1]
            argv = core.compose("logs", "--no-color", "--tail", str(tail), name)
            code, out, err = core.run_capture(
                argv, cwd=self.project.repo, env=self.project.env, timeout=10
            )
            if code != 0:
                reason = (err.strip().splitlines() or ["docker compose logs failed"])[-1]
                return base | {"lines": [], "truncated": False, "error": reason}
            lines = [core.clean_line(line) for line in out.splitlines()][-tail:]
            return base | {"lines": lines, "truncated": len(lines) >= tail, "error": ""}
        path = self.project.repo / item["path"]
        if not path.is_file():
            return base | {"lines": [], "truncated": False, "error": "There is no log yet."}
        try:
            lines, truncated = tail_file(path, tail)
        except OSError as exc:
            return base | {"lines": [], "truncated": False, "error": str(exc)}
        return base | {"lines": lines, "truncated": truncated, "error": ""}

    # the features
    def _get(self, path: str, headers: Mapping[str, str] | None = None) -> Any:
        url = self.project.product_internal_url + path
        request = urllib.request.Request(url, headers=dict(headers or {}))
        with core._LOCAL.open(request, timeout=2.0) as response:
            return json.loads(response.read(1_000_000).decode("utf-8"))

    def _tenant(self) -> dict[str, str]:
        with contextlib.suppress(OSError, ValueError):
            state = json.loads((self.project.repo / "var/seed/last.json").read_text("utf-8"))
            if isinstance(state, dict) and isinstance(state.get("tenant_id"), str):
                return state
        return {}

    def features(
        self, status: core.Status | None, last_check: Mapping[str, Any] | None
    ) -> list[dict[str, Any]]:
        up = bool(status and status.up.get("product.internal"))
        links = self._admin_links()
        features = [
            self._route_feature(
                "review-queue",
                "Review queue",
                "Draft rules waiting for a person to check them.",
                "/v1/rulebook/review/stats",
                up,
                links,
                self._review_numbers,
            ),
            self._route_feature(
                "pipeline-tasks",
                "Pipeline tasks",
                "Documents the pipeline could not handle on its own, by kind.",
                "/v1/pipeline/tasks",
                up,
                links,
                self._task_numbers,
            ),
            self._route_feature(
                "fan-out",
                "Fan-out",
                "Published rules being applied to every business, and whether that is on hold.",
                "/v1/applicability-engine/fan-outs",
                up,
                links,
                self._fanout_numbers,
            ),
            self._route_feature(
                "runs",
                "Eval runs",
                "Stored runs of the evaluation harness and whether their gates passed.",
                "/v1/eval/runs",
                up,
                links,
                self._eval_numbers,
            ),
            self._route_feature(
                "changes",
                "Rule changes",
                "Published changes to the rulebook.",
                "/v1/changes",
                up,
                links,
                self._change_numbers,
            ),
            self._route_feature(
                "obligations",
                "Obligations",
                "What the sample business has to do, and by when.",
                "/v1/obligation/obligations",
                up,
                links,
                self._obligation_numbers,
            ),
            self._notifications(links),
            self._dead_outbox(status),
            self._flags_feature(links),
            self._check_feature(last_check),
            self._eval_report(),
        ]
        return features

    def _admin_links(self) -> dict[str, list[dict[str, Any]]]:
        screens = {screen.id: screen for screen in self.project.screens}
        web = self.project.product_web_url
        links: dict[str, list[dict[str, Any]]] = {}
        for feature, ids in FEATURE_ADMIN.items():
            for screen_id in ids:
                screen = screens.get(screen_id)
                if screen is None or not screen.static:
                    continue
                links.setdefault(feature, []).append(
                    {
                        "label": screen.title,
                        "url": web + screen.route,
                        "live": screen.status == "live",
                    }
                )
        return links

    def _route_feature(
        self,
        feature: str,
        title: str,
        summary: str,
        route: str,
        up: bool,
        links: Mapping[str, list[dict[str, Any]]],
        numbers: Callable[[], list[dict[str, Any]]],
    ) -> dict[str, Any]:
        base = {
            "id": feature,
            "title": title,
            "summary": summary,
            "links": links.get(feature, []),
            "source": f"GET {route}",
            "numbers": [],
            "note": "",
        }
        if route not in self.routes:
            return base | {
                "state": "not-built",
                "note": "Not built yet: no service serves this route.",
            }
        if not up:
            return base | {
                "state": "not-running",
                "note": "Start the product to see live numbers.",
            }
        try:
            return base | {"state": "live", "numbers": numbers()}
        except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as exc:
            return base | {
                "state": "error",
                "note": "The product did not answer this read.",
                "error": str(exc),
            }

    def _review_numbers(self) -> list[dict[str, Any]]:
        stats = self._get("/v1/rulebook/review/stats")
        by_status = stats.get("by_status", {})
        age = stats.get("oldest_open_age_seconds") or 0
        return [
            {"label": "Waiting", "value": by_status.get("open", 0), "hint": "drafts in the queue"},
            {"label": "Being reviewed", "value": by_status.get("claimed", 0), "hint": "claimed"},
            {"label": "Decided", "value": by_status.get("decided", 0), "hint": "all time"},
            {"label": "Oldest waiting", "value": core.format_seconds(age), "hint": "time waiting"},
        ]

    def _task_numbers(self) -> list[dict[str, Any]]:
        page = self._get("/v1/pipeline/tasks?status=open&limit=200")
        kinds = collections.Counter(str(item.get("kind", "other")) for item in page["items"])
        numbers = [{"label": "Open tasks", "value": sum(kinds.values()), "hint": "first 200"}]
        numbers += [
            {"label": kind, "value": count, "hint": "open"} for kind, count in kinds.items()
        ]
        return numbers

    def _fanout_numbers(self) -> list[dict[str, Any]]:
        hold = self._get("/v1/applicability-engine/fan-out-hold")
        page = self._get("/v1/applicability-engine/fan-outs?limit=50")
        states = collections.Counter(str(item.get("status", "unknown")) for item in page["items"])
        numbers = [
            {
                "label": "Hold",
                "value": "on" if hold.get("held") else "off",
                "hint": hold.get("reason") or "fan-outs run",
            },
            {"label": "Runs", "value": sum(states.values()), "hint": "the last 50"},
        ]
        numbers += [
            {"label": state, "value": count, "hint": "runs"} for state, count in states.items()
        ]
        return numbers

    def _eval_numbers(self) -> list[dict[str, Any]]:
        runs = self._get("/v1/eval/runs?limit=20")
        items = runs if isinstance(runs, list) else runs.get("items", [])
        numbers = [{"label": "Stored runs", "value": len(items), "hint": "the last 20"}]
        if items:
            latest = items[0]
            passed = latest.get("passed")
            numbers.append(
                {
                    "label": "Latest",
                    "value": "passed" if passed else ("failed" if passed is False else "stored"),
                    "hint": str(latest.get("suite", "")),
                }
            )
        return numbers

    def _change_numbers(self) -> list[dict[str, Any]]:
        tenant = self._tenant()
        headers = {"x-tenant-id": tenant["tenant_id"]} if tenant else {}
        page = self._get("/v1/changes?limit=100", headers)
        count = len(page["items"])
        more = "+" if page.get("next_cursor") else ""
        return [{"label": "Published changes", "value": f"{count}{more}", "hint": "newest 100"}]

    def _obligation_numbers(self) -> list[dict[str, Any]]:
        tenant = self._tenant()
        business = tenant.get("registration_node_id") or tenant.get("entity_node_id")
        if not tenant or not business:
            raise ValueError("no sample business yet: load demo data or fill the product")
        items = self._get(
            f"/v1/obligation/obligations?business_id={urllib.parse.quote(str(business))}",
            {"x-tenant-id": tenant["tenant_id"]},
        )
        rows = items if isinstance(items, list) else items.get("items", [])
        states = collections.Counter(str(row.get("status", "unknown")) for row in rows)
        numbers = [{"label": "Obligations", "value": len(rows), "hint": "the sample business"}]
        numbers += [{"label": state, "value": count, "hint": ""} for state, count in states.items()]
        return numbers

    def _notifications(self, links: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
        sink = self.project.repo / "var" / "notification" / "sink.jsonl"
        base = {
            "id": "notifications",
            "title": "Notifications sent",
            "summary": "Messages the product sent through its local sink instead of email or "
            "WhatsApp.",
            "links": links.get("notifications", []),
            "source": "var/notification/sink.jsonl",
        }
        if not sink.is_file():
            return base | {
                "state": "not-running",
                "numbers": [],
                "note": "Nothing has been sent yet.",
            }
        try:
            with sink.open("rb") as handle:
                count = sum(1 for _ in handle)
            modified = sink.stat().st_mtime
        except OSError as exc:
            return base | {"state": "not-running", "numbers": [], "note": str(exc)}
        age = core.format_seconds(max(time.time() - modified, 0))
        return base | {
            "state": "live",
            "numbers": [
                {"label": "Sent", "value": count, "hint": "through the sink"},
                {"label": "Last one", "value": f"{age} ago", "hint": ""},
            ],
            "note": "",
        }

    def _dead_outbox(self, status: core.Status | None) -> dict[str, Any]:
        base = {
            "id": "dead-outbox",
            "title": "Stuck events (dead outbox)",
            "summary": "Events a service saved but could not publish after every retry.",
            "links": [],
            "source": "outbox_event rows with status dead, per service schema",
        }
        if not (status and status.docker):
            return base | {
                "state": "not-running",
                "numbers": [],
                "note": "Start the databases to read it.",
            }
        sql = (
            "SET default_transaction_read_only = on; SELECT table_schema FROM "
            "information_schema.tables WHERE table_name = 'outbox_event' ORDER BY 1"
        )
        user = self.project.env.get("POSTGRES_USER") or "cw"
        database = self.project.env.get("POSTGRES_DB") or "compliancewatch"
        env_file = core.read_env_file(self.project.repo / ".env")
        user = env_file.get("POSTGRES_USER", user)
        database = env_file.get("POSTGRES_DB", database)
        psql = core.compose("exec", "-T", "postgres", "psql", "-U", user, "-d", database, "-At")
        code, out, err = core.run_capture(
            (*psql, "-c", sql), cwd=self.project.repo, env=self.project.env, timeout=8
        )
        schemas = [s for s in out.split() if re.fullmatch(r"[a-z_][a-z0-9_]*", s)]
        if code != 0:
            reason = (err.strip().splitlines() or ["psql failed"])[-1]
            return base | {"state": "not-running", "numbers": [], "note": reason}
        if not schemas:
            return base | {"state": "live", "numbers": [], "note": "No service has an outbox yet."}
        union = " UNION ALL ".join(
            f"SELECT '{s}', count(*) FILTER (WHERE status = 'dead') FROM {s}.outbox_event"
            for s in schemas
        )
        code, out, err = core.run_capture(
            (*psql, "-c", f"SET default_transaction_read_only = on; {union}"),
            cwd=self.project.repo,
            env=self.project.env,
            timeout=8,
        )
        if code != 0:
            reason = (err.strip().splitlines() or ["psql failed"])[-1]
            return base | {"state": "not-running", "numbers": [], "note": reason}
        counts: dict[str, int] = {}
        for line in out.splitlines():
            schema, _, count = line.partition("|")
            if count.strip().isdigit():
                counts[schema] = int(count)
        numbers = [
            {"label": schema, "value": count, "hint": "dead events"}
            for schema, count in counts.items()
        ]
        total = sum(counts.values())
        return base | {
            "state": "live",
            "numbers": [{"label": "Total", "value": total, "hint": "dead events"}, *numbers],
            "note": "",
        }

    def _flags_feature(self, links: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
        rows, error = self.flags()
        changed = [row for row in rows if row.value is not None and row.value != row.default]
        return {
            "id": "flags",
            "title": "Feature flags",
            "summary": "Switches that turn features on or off, from the flag registry and .env.",
            "state": "live" if not error else "not-running",
            "numbers": [
                {"label": "Flags", "value": len(rows), "hint": "in the registry"},
                {"label": "Changed here", "value": len(changed), "hint": "set in .env"},
            ],
            "links": links.get("flags", []),
            "note": error,
            "source": "packages/flags/registry.json",
        }

    def _check_feature(self, last: Mapping[str, Any] | None) -> dict[str, Any]:
        base = {
            "id": "product-check",
            "title": "Last product check",
            "summary": "The last time this app checked the product works, step by step.",
            "links": [],
            "source": "this app's runs",
        }
        if last is None:
            return base | {
                "state": "not-running",
                "numbers": [],
                "note": "Not run since this app opened. Check the product works runs it.",
            }
        steps = last.get("steps", [])
        passed = sum(1 for step in steps if step.get("state") == "ok")
        return base | {
            "state": "live",
            "numbers": [
                {"label": "Result", "value": last.get("state", ""), "hint": ""},
                {"label": "Steps passed", "value": f"{passed} of {len(steps)}", "hint": ""},
            ],
            "note": "",
        }

    def _eval_report(self) -> dict[str, Any]:
        base = {
            "id": "eval-report",
            "title": "Last eval report",
            "summary": "The newest report the eval harness wrote.",
            "links": [],
            "source": "evals/reports",
        }
        folder = self.project.repo / "evals" / "reports"
        reports = (
            sorted(
                (p for p in folder.glob("**/*") if p.is_file() and not p.name.startswith(".")),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if folder.is_dir()
            else []
        )
        if not reports:
            return base | {
                "state": "not-running",
                "numbers": [],
                "note": "No report yet: Run the evals writes one.",
            }
        newest = reports[0]
        age = core.format_seconds(max(time.time() - newest.stat().st_mtime, 0))
        return base | {
            "state": "live",
            "numbers": [
                {"label": "Report", "value": newest.name, "hint": f"{age} ago"},
                {"label": "Reports", "value": len(reports), "hint": "in evals/reports"},
            ],
            "note": "",
        }

    def github(self, git: core.GitState | None) -> dict[str, Any]:
        project = self.project
        if self._remote is None:
            self._remote = core.probe_remote(project.repo, project.env)
        base = self._remote
        branch = git.branch if git else ""
        links = (
            [{"label": label, "url": url} for label, url in core.github_links(base, branch)]
            if base
            else []
        )
        info: dict[str, Any] = {
            "available": False,
            "reason": "",
            "repo_url": base,
            "branch": branch,
            "links": links,
            "prs": [],
        }
        if base is None:
            return info | {"reason": "This checkout's origin is not a GitHub repository."}
        gh = shutil.which("gh", path=project.env.get("PATH"))
        if gh is None:
            return info | {"reason": "The GitHub command-line tool (gh) is not installed."}
        code, _, _ = core.run_capture(
            (gh, "auth", "status"), cwd=project.repo, env=project.env, timeout=8
        )
        if code != 0:
            return info | {"reason": "gh is not signed in. Run gh auth login in a terminal."}
        fields = "number,title,url,headRefName,statusCheckRollup"
        code, out, err = core.run_capture(
            (gh, "pr", "list", "--state", "open", "--limit", "10", "--json", fields),
            cwd=project.repo,
            env=project.env,
            timeout=12,
        )
        if code != 0:
            reason = (err.strip().splitlines() or ["gh pr list failed"])[-1]
            return info | {"reason": reason}
        try:
            prs = json.loads(out)
        except ValueError:
            return info | {"reason": "gh answered something unexpected."}
        return info | {
            "available": True,
            "prs": [
                {
                    "number": pr.get("number"),
                    "title": pr.get("title", ""),
                    "url": pr.get("url", ""),
                    "branch": pr.get("headRefName", ""),
                    "checks": checks_state(pr.get("statusCheckRollup") or []),
                }
                for pr in prs
                if isinstance(pr, dict)
            ],
        }


def checks_state(rollup: Sequence[Mapping[str, Any]]) -> str:
    """A pull request's checks in one word: failing, pending, passing or none."""
    if not rollup:
        return "none"
    states = {
        str(item.get("conclusion") or item.get("state") or item.get("status") or "").upper()
        for item in rollup
    }
    if states & {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}:
        return "failing"
    if states & {"PENDING", "IN_PROGRESS", "QUEUED", "WAITING", "EXPECTED", ""}:
        return "pending"
    return "passing"


# ---- HTTP --------------------------------------------------------------------------------------

ROUTES: Final[tuple[tuple[str, re.Pattern[str], str], ...]] = tuple(
    (method, re.compile(pattern), name)
    for method, pattern, name in (
        ("GET", r"/api/meta", "meta"),
        ("GET", r"/api/status", "status"),
        ("GET", r"/api/actions", "actions"),
        ("POST", r"/api/actions/(?P<id>[^/]+)/preview", "preview"),
        ("POST", r"/api/actions/(?P<id>[^/]+)/run", "run"),
        ("GET", r"/api/runs", "runs"),
        ("GET", r"/api/runs/(?P<run_id>[^/]+)", "run_detail"),
        ("POST", r"/api/runs/(?P<run_id>[^/]+)/cancel", "cancel"),
        ("GET", r"/api/events", "events"),
        ("POST", r"/api/events/ticket", "ticket"),
        ("POST", r"/api/launch-code", "launch_code"),
        ("GET", r"/api/features", "features"),
        ("GET", r"/api/flags", "flags"),
        ("GET", r"/api/processes", "processes"),
        ("GET", r"/api/processes/(?P<pid>[0-9]{1,9})/stop-preview", "stop_preview"),
        ("POST", r"/api/processes/(?P<pid>[0-9]{1,9})/stop", "stop_process"),
        ("GET", r"/api/logs", "log_sources"),
        ("GET", r"/api/logs/(?P<source>[^/]+)", "log"),
        ("GET", r"/api/kafka", "kafka"),
        ("POST", r"/api/kafka/refresh", "kafka_refresh"),
        ("GET", r"/api/docs", "docs"),
        ("POST", r"/api/docs/(?P<doc>[^/]+)/open", "open_doc"),
        ("GET", r"/api/github", "github"),
        ("POST", r"/api/heartbeat", "heartbeat"),
        ("GET", r"/api/prefs", "prefs"),
        ("PUT", r"/api/prefs", "save_prefs"),
        ("POST", r"/api/demo/state", "demo_state"),
    )
)


class PanelServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    request_queue_size = 64  # the window fetches its ~25 modules at once; 5 drops some on macOS
    app: App

    def handle_error(self, request: Any, client_address: Any) -> None:
        """A client that went away is not news; anything else is logged, without the request."""
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        log("connection failed:\n" + traceback.format_exc())


class Handler(BaseHTTPRequestHandler):
    server: PanelServer
    protocol_version = "HTTP/1.1"
    server_version = "ComplianceWatchControl"
    sys_version = ""
    timeout = 120  # an idle kept-alive connection lets go of its thread after two minutes

    # no request lines on stderr: they would carry query strings (an EventSource's ticket)
    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        return

    def log_message(self, format: str, *args: Any) -> None:
        return

    @property
    def app(self) -> App:
        return self.server.app

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def do_OPTIONS(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle()

    def _handle(self) -> None:
        try:
            self._guard()
            url = urllib.parse.urlsplit(self.path)
            if url.path.startswith("/api/") or url.path == "/api":
                self._api(url)
            elif self.command == "GET":
                self._static(url.path)
            else:
                raise ApiError(405, "method-not-allowed", "That method is not allowed here.")
        except ApiError as refusal:
            self._send_json(refusal.status, refusal.body(), close=refusal.status in (411, 413))
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            log("request failed:\n" + traceback.format_exc())
            failure = ApiError(
                500,
                "internal",
                "Something went wrong in the control app.",
                traceback.format_exc(limit=3),
            )
            with contextlib.suppress(OSError):
                self._send_json(500, failure.body())

    def _guard(self) -> None:
        if self.headers.get("Host", "") != self.app.host_header:
            raise ApiError(403, "bad-host", "This address is not allowed.")
        origin = self.headers.get("Origin")
        if origin is not None and origin != self.app.origin:
            raise ApiError(403, "bad-origin", "Requests from other sites are not allowed.")
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site not in ("same-origin", "none"):
            raise ApiError(403, "bad-origin", "Requests from other sites are not allowed.")

    def _launch(self) -> None:
        """The one route without the token: a page of this helper (its own Origin, which a
        browser always sends on a POST) swaps a launch code for the token."""
        if self.command != "POST":
            raise ApiError(405, "method-not-allowed", "That method is not allowed here.")
        if self.headers.get("Origin") != self.app.origin:
            raise ApiError(403, "bad-origin", "Requests from other sites are not allowed.")
        answer = self.app.launch(self._body())
        self.app.lifetime.touch()
        self._send_json(200, answer)

    def _authorised(self, url: urllib.parse.SplitResult) -> bool:
        given = self.headers.get("X-Panel-Token")
        if given is not None:
            return hmac.compare_digest(given.encode(), self.app.token.encode())
        if url.path == "/api/events" and self.command == "GET":
            ticket = urllib.parse.parse_qs(url.query).get("ticket", [""])[0]
            return self.app.tickets.take(ticket) is not None
        return False

    def _api(self, url: urllib.parse.SplitResult) -> None:
        if self.command not in ("GET", "POST", "PUT"):
            raise ApiError(405, "method-not-allowed", "That method is not allowed here.")
        if url.path == "/api/launch":
            self._launch()
            return
        if not self._authorised(url):
            raise ApiError(
                401,
                "unauthorized",
                "This window is not connected to the control app.",
                "The request carried no token, or the wrong one.",
                "Close this window and open the app again.",
            )
        self.app.lifetime.touch()
        route, match = None, None
        methods = set()
        for method, pattern, name in ROUTES:
            found = pattern.fullmatch(url.path)
            if found:
                methods.add(method)
                if method == self.command:
                    route, match = name, found
                    break
        if route is None or match is None:
            if methods:
                raise ApiError(405, "method-not-allowed", "That method is not allowed here.")
            raise ApiError(404, "not-found", "There is no such address.", url.path)
        body = self._body()
        args = {key: urllib.parse.unquote(value) for key, value in match.groupdict().items()}
        query = urllib.parse.parse_qs(url.query)
        if route == "events":
            self._events()
            return
        status, answer = self._dispatch(route, args, query, body)
        self._send_json(status, answer)

    def _dispatch(
        self,
        route: str,
        args: Mapping[str, str],
        query: Mapping[str, list[str]],
        body: Mapping[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        app = self.app
        if route == "meta":
            return 200, app.meta()
        if route == "status":
            return 200, app.status_body()
        if route == "actions":
            return 200, app.actions()
        if route == "preview":
            return 200, app.preview(args["id"], body)
        if route == "run":
            return app.run(args["id"], body)
        if route == "runs":
            limit = _int(query, "limit", 20, 1, RUN_HISTORY)
            return 200, {"runs": app.runs.recent(limit)}
        if route == "run_detail":
            detail = app.runs.detail(args["run_id"])
            if detail is None:
                raise ApiError(404, "not-found", "There is no such run.", args["run_id"])
            return 200, detail
        if route == "cancel":
            return 200, app.cancel(args["run_id"])
        if route == "launch_code":
            return 200, {"code": app.launches.issue(), "expires_in": int(LAUNCH_SECONDS)}
        if route == "ticket":
            return 200, {"ticket": app.tickets.issue(), "expires_in": int(TICKET_SECONDS)}
        if route == "features":
            return 200, app.features()
        if route == "flags":
            return 200, app.flags()
        if route == "processes":
            return 200, app.processes()
        if route == "stop_preview":
            return 200, app.stop_preview(int(args["pid"]))
        if route == "stop_process":
            return app.stop_process(int(args["pid"]), body)
        if route == "log_sources":
            return 200, app.log_sources()
        if route == "log":
            return 200, app.read_log(args["source"], _int(query, "tail", 500, 1, RUN_LINES))
        if route == "kafka":
            return 200, app.kafka()
        if route == "kafka_refresh":
            return 200, app.kafka_refresh()
        if route == "docs":
            return 200, app.docs()
        if route == "open_doc":
            return 200, app.open_doc(args["doc"])
        if route == "github":
            return 200, app.github()
        if route == "heartbeat":
            return 200, app.heartbeat()
        if route == "prefs":
            return 200, app.prefs.get()
        if route == "save_prefs":
            return 200, app.save_prefs(body)
        if route == "demo_state":
            return 200, app.demo_state(body)
        raise ApiError(404, "not-found", "There is no such address.")

    def _body(self) -> dict[str, Any]:
        if self.command not in ("POST", "PUT"):
            return {}
        if self.headers.get("Transfer-Encoding"):
            raise ApiError(411, "length-required", "Send the body with a Content-Length.")
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            return {}
        try:
            length = int(length_header)
        except ValueError as exc:
            raise ApiError(400, "bad-request", "The Content-Length is not a number.") from exc
        if length < 0:
            raise ApiError(400, "bad-request", "The Content-Length is not a number.")
        if length > MAX_BODY:
            raise ApiError(
                413, "too-large", "The request is too large.", f"at most {MAX_BODY} bytes"
            )
        if length == 0:
            return {}
        if self.headers.get_content_type() != "application/json":
            raise ApiError(415, "unsupported-media-type", "Send the body as application/json.")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise ApiError(400, "bad-json", "The body is not valid JSON.", str(exc)) from exc
        if not isinstance(data, dict):
            raise ApiError(400, "bad-json", "The body must be a JSON object.")
        return data

    def _common_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")

    def _send_json(self, status: int, body: Mapping[str, Any], close: bool = False) -> None:
        data = dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._common_headers()
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _static(self, path: str) -> None:
        relative = urllib.parse.unquote(path).lstrip("/") or "index.html"
        parts = relative.split("/")
        if (
            any(not part or part.startswith(".") for part in parts)
            or "\\" in relative
            or "\x00" in relative
        ):
            raise ApiError(404, "not-found", "There is no such file.")
        target = (self.app.ui_dir / relative).resolve()
        if not target.is_relative_to(self.app.ui_dir) or not target.is_file():
            raise ApiError(404, "not-found", "There is no such file.")
        content_type = STATIC_TYPES.get(target.suffix.lower())
        if content_type is None:
            raise ApiError(404, "not-found", "There is no such file.")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._common_headers()
        if target.suffix.lower() == ".html":
            self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(data)

    def _events(self) -> None:
        last_header = self.headers.get("Last-Event-ID")
        last_id = int(last_header) if last_header and last_header.isdigit() else None
        sub, replay = self.app.hub.subscribe(last_id)
        self.close_connection = True
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            self._write(b"retry: 3000\n\n")
            self._write(frame("hello", self.app.hello(resync=replay is None)))
            if replay:
                for event in replay:
                    self._write(event.frame())
            else:
                self._write(frame("status", self.app.status_body()))
            self.app.poller.poke("status")
            while not sub.closed:
                try:
                    item = sub.queue.get(timeout=PING_SECONDS)
                except queue.Empty:
                    self._write(b": ping\n\n")
                    continue
                if item is None:
                    break
                self._write(item.frame())
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.app.hub.unsubscribe(sub)

    def _write(self, data: bytes) -> None:
        self.wfile.write(data)
        self.wfile.flush()


def _int(query: Mapping[str, list[str]], name: str, default: int, low: int, high: int) -> int:
    values = query.get(name)
    if not values:
        return default
    try:
        return max(low, min(high, int(values[0])))
    except ValueError as exc:
        raise ApiError(400, "bad-params", f"{name} must be a number.") from exc


# ---- running it --------------------------------------------------------------------------------


def make_server(
    backend: Backend,
    *,
    port: int = 0,
    prefs: Prefs,
    ui_dir: Path = UI_DIR,
    idle_seconds: float = IDLE_EXIT_SECONDS,
) -> PanelServer:
    server = PanelServer(("127.0.0.1", port), Handler)
    token = secrets.token_urlsafe(32)
    server.app = App(
        backend,
        token=token,
        port=server.server_address[1],
        prefs=prefs,
        ui_dir=ui_dir,
        idle_seconds=idle_seconds,
    )
    return server


@contextlib.contextmanager
def serving(server: PanelServer, poll_interval: float = 0.5) -> Iterator[PanelServer]:
    """The server answering on a thread, with its poller running; shut down after."""
    thread = threading.Thread(
        target=server.serve_forever, args=(poll_interval,), daemon=True, name="http"
    )
    thread.start()
    server.app.poller.start()
    try:
        yield server
    finally:
        server.app.shutdown()
        server.shutdown()
        server.server_close()


def stdin_is_pipe() -> bool:
    try:
        mode = os.fstat(sys.stdin.fileno()).st_mode
    except (OSError, ValueError):
        return False
    return stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode)


def watch_stdin(on_eof: Callable[[], None], fd: int | None = None) -> None:
    """Calls ``on_eof`` when standard input (or ``fd``), a pipe from the shell, reaches end of
    file."""
    with contextlib.suppress(OSError, ValueError):
        source = sys.stdin.fileno() if fd is None else fd
        while os.read(source, 4096):
            pass
    on_eof()


def hand_off_line(port: int, token: str, *, opened: bool, tty: bool | None = None) -> str:
    """What goes to stdout: the one JSON line a program reads, or, when a person runs it in a
    terminal and it opens the window itself, plain words without the token."""
    if tty is None:
        tty = sys.stdout.isatty()
    if tty and opened:
        return (
            f"ComplianceWatch Control is open in your browser (http://127.0.0.1:{port}). "
            "Press Ctrl-C to stop it.\n"
        )
    return json.dumps({"port": port, "token": token}) + "\n"


CHROME_APPS: Final = (
    Path("/Applications/Google Chrome.app"),
    Path.home() / "Applications" / "Google Chrome.app",
)


def open_window(url: str, *, app: bool) -> None:
    """Opens the UI: in Google Chrome's app mode (a window without tabs or address bar) when
    ``app`` and Chrome is installed, else in the default browser."""
    chrome = next((path for path in CHROME_APPS if path.is_dir()), None) if app else None
    if chrome is None:
        webbrowser.open(url)
        return
    with contextlib.suppress(OSError):
        subprocess.Popen(
            ("/usr/bin/open", "-na", str(chrome), "--args", f"--app={url}"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ComplianceWatch Control's local helper.")
    parser.add_argument("--demo", action="store_true", help="canned data and simulated runs")
    parser.add_argument(
        "--open",
        nargs="?",
        const="browser",
        choices=("browser", "app"),
        help="open the window: in the default browser, or (app) in Google Chrome's app mode",
    )
    parser.add_argument(
        "--detach",
        action="store_true",
        help="keep running when the parent exits (the app's browser fallback); it still stops "
        "ten minutes after the last window closes",
    )
    parser.add_argument("--port", type=int, default=0, help="the port (default: a free one)")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.demo:
        import panel_demo

        backend: Backend = panel_demo.DemoBackend()
        prefs = Prefs(None)
    else:
        backend = RealBackend()
        path = os.environ.get(PREFS_ENV)
        prefs = Prefs(Path(path) if path else DEFAULT_PREFS_PATH)
    server = make_server(backend, port=args.port, prefs=prefs)
    app = server.app
    stop = threading.Event()
    reasons: list[str] = []

    def halt(reason: str) -> None:
        reasons.append(reason)
        stop.set()

    parent = os.getppid()
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, lambda number, _: halt(signal.Signals(number).name))
    with serving(server):
        sys.stdout.write(hand_off_line(app.port, app.token, opened=bool(args.open)))
        sys.stdout.flush()
        if stdin_is_pipe():
            threading.Thread(
                target=watch_stdin, args=(lambda: halt("stdin closed"),), daemon=True, name="stdin"
            ).start()
        if args.open:
            open_window(app.launch_url(), app=args.open == "app")
        while not stop.wait(1.0):
            if not args.detach and os.getppid() != parent:
                halt("its parent exited")
            elif app.lifetime.expired():
                halt("ten minutes passed without a window")
        log(f"exiting: {reasons[0] if reasons else 'stopped'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
