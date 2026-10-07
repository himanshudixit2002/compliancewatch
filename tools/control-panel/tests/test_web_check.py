"""Click through the web app on a test copy of its own: the steps the app performs itself, with a
made-up process table (ps and lsof answer from fixtures) and no program run. What it refuses
before anything starts (other browser tests, no browser, a port in use), the browser it chooses
(Playwright's own Chromium, else Google Chrome), the pid files it never acts on, and the clean-up
that stops the test copy and, when the browser tests left it, their web app."""

from __future__ import annotations

import json
import os
import socket
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import panel_core as core
import pytest

DOWN = (
    "make",
    "web-stack-down",
    "STORE=memory",
    "WEB_STACK_DIR=var/web-stack-check",
    "SERVICE_PORT_BASE=9400",
)
E2E = (
    "make",
    "web-e2e",
    "STORE=memory",
    "WEB_STACK_DIR=var/web-stack-check",
    "SERVICE_PORT_BASE=9400",
    "WEB_PORT=3410",
)


@dataclass(frozen=True)
class P:
    """One process of the made-up table: its command, name and working directory as ps and lsof
    report them, how long it has run, and the port it listens on."""

    pid: int
    ppid: int
    command: str
    cwd: str
    name: str = ""
    etime: str = "05:00"
    port: int | None = None


def table(procs: Sequence[P]) -> tuple[str, str, str]:
    ps = "".join(f"{p.pid} {p.ppid} {p.pid} {p.etime} {p.command}\n" for p in procs)
    names = "".join(
        f"p{p.pid}\nc{p.name or Path(p.command.split()[0]).name}\nn{p.cwd}\n" for p in procs
    )
    listen = "".join(
        f"p{p.pid}\nc{p.name or 'node'}\nn127.0.0.1:{p.port}\n" for p in procs if p.port
    )
    return ps, names, listen


class Ctx:
    """A step context over the made-up table: it runs nothing and records what it would run."""

    def __init__(self, call: core.Call, procs: Sequence[P] = (), ps_fails: bool = False) -> None:
        self.call = call
        self.ps, self.names, self.listen = table(procs)
        self.ps_fails = ps_fails
        self.lines: list[str] = []
        self.ran: list[tuple[str, ...]] = []
        self.envs: list[tuple[tuple[str, str], ...]] = []
        self.read: list[tuple[str, ...]] = []

    def log(self, text: str, tag: str | None = None) -> None:
        self.lines.append(text)

    def allows(self, argv: Sequence[str]) -> bool:
        return tuple(argv) in self.call.commands

    def run(self, argv: Sequence[str], env: Iterable[tuple[str, str]] = ()) -> bool:
        assert self.allows(argv), argv
        self.ran.append(tuple(argv))
        self.envs.append(tuple(env))
        return True

    def capture(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        stdin_path: Path | None = None,
    ) -> tuple[int | None, str, str]:
        assert self.allows(argv), argv
        self.read.append(tuple(argv))
        if tuple(argv) == core.PS_ARGV:
            return (1, "", "ps: failed") if self.ps_fails else (0, self.ps, "")
        if tuple(argv) == core.lsof_cwd_argv():
            return 0, self.names, ""
        if tuple(argv) == core.lsof_listen_argv():
            return 0, self.listen, ""
        raise AssertionError(f"unexpected program {argv}")

    def wait(self, seconds: float) -> bool:
        return True

    @property
    def cancelled(self) -> bool:
        return False


@pytest.fixture
def plans(tmp_path: Path) -> core.Plans:
    project = core.Project(
        repo=tmp_path,
        env=core.program_env({"PATH": "/usr/bin:/bin", "HOME": "/Users/dev"}),
        ports=core.resolve_ports({}, {}),
        make_targets={},
        checks=[],
        check_steps=list(core.CHECK_STEPS_FALLBACK),
        screens=list(core.SCREENS_FALLBACK),
        workers=[],
        relays=[],
    )
    registry = core.Registry(tmp_path / "var" / "control-panel")
    return core.Plans(project, core.BackgroundManager(tmp_path, project.env, registry))


@pytest.fixture
def free(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Every port answers as free, but those the test puts in the list."""
    busy: list[int] = []
    monkeypatch.setattr(core, "port_answers", lambda port, timeout=0.3: port in busy)
    return busy


CHROMIUM = core.E2EBrowser("", "the browser tests use Playwright's own Chromium, downloaded here")


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch) -> list[core.E2EBrowser]:
    """The browser the first step finds: Playwright's own Chromium, unless the test says."""
    found = [CHROMIUM]
    monkeypatch.setattr(core, "e2e_browser", lambda repo, settings, **kwargs: found[0])
    return found


def steps(plans: core.Plans) -> dict[str, core.Call]:
    return {step.label: step for step in plans.web_check().steps if isinstance(step, core.Call)}


def ready(plans: core.Plans) -> core.Call:
    return steps(plans)["check that the test copy can start"]


def uvicorn(repo: Path, service: str, port: int) -> str:
    package = core.service_package(service)
    return f"uv run --package compliancewatch-{service} uvicorn {package}.main:app --port {port}"


def pid_files(repo: Path, **pids: int) -> Path:
    folder = repo / "var" / "web-stack-check"
    folder.mkdir(parents=True, exist_ok=True)
    for service, pid in pids.items():
        (folder / f"{service.replace('_', '-')}.pid").write_text(f"{pid}\n")
    return folder


def test_a_port_answers_while_something_listens_on_it() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert core.port_answers(port)
    assert not core.port_answers(port)


def test_it_refuses_while_another_browser_test_run_works_in_this_checkout(
    plans: core.Plans, tmp_path: Path, free: list[int]
) -> None:
    web = str(tmp_path / "apps" / "web")
    playwright = f"node {web}/node_modules/.bin/../@playwright/test/cli.js test --project=chromium"
    procs = [
        P(400, 1, "/Applications/Claude.app/Contents/MacOS/claude", "/Users/dev", "claude"),
        P(401, 400, "make web-e2e SERVICE_PORT_BASE=9200 WEB_PORT=3217", str(tmp_path), "make"),
        P(402, 401, "node /opt/homebrew/bin/pnpm --filter web e2e", web, "node"),
        P(403, 402, playwright, web, "node"),
    ]
    call = ready(plans)
    ctx = Ctx(call, procs)
    assert call.fn(ctx) is False
    assert ctx.lines[0].startswith(
        "error: browser tests are already running in this checkout: pid 403, "
    )
    assert "They share apps/web/test-results with this check" in ctx.lines[0]
    assert ctx.ran == []
    # what Claude Code runs counts too: it is another session's work that a new run would break
    snapshot = core.probe_processes(tmp_path, {}, plans.manager.registry, ctx.capture)
    assert 403 in snapshot.guarded
    assert core.browser_test_runs(snapshot, tmp_path) == [403]


def test_it_leaves_alone_the_test_copy_of_another_web_check(
    plans: core.Plans, tmp_path: Path, free: list[int]
) -> None:
    # another control window's check (or one run by hand) is seeding its test copy
    folder = pid_files(tmp_path, identity=201)
    seed = "make web-seed STORE=memory WEB_STACK_DIR=var/web-stack-check SERVICE_PORT_BASE=9400"
    procs = [
        P(201, 1, uvicorn(tmp_path, "identity", 9401), str(tmp_path), "uv"),
        P(700, 1, seed, str(tmp_path), "make"),
    ]
    call = ready(plans)
    ctx = Ctx(call, procs)
    assert call.fn(ctx) is False
    assert ctx.lines == [
        "error: the web check is already running in this checkout: pid 700, make web-seed "
        "STORE=memory WEB_STACK_DIR=var/web-stack-check SERVICE_…. Its test copy is left alone: "
        "wait for it to finish, then try again."
    ]
    assert ctx.ran == []
    assert (folder / "identity.pid").exists()


def test_browser_tests_elsewhere_do_not_count(plans: core.Plans, tmp_path: Path) -> None:
    # the control app's own window tests run Playwright from the checkout's root, with their
    # results under var/
    ui_tests = f"node {tmp_path}/apps/web/node_modules/@playwright/test/cli.js test --config x.mjs"
    ctx = Ctx(ready(plans), [P(500, 1, ui_tests, str(tmp_path), "node")])
    snapshot = core.probe_processes(tmp_path, {}, plans.manager.registry, ctx.capture)
    assert 500 in snapshot.project
    assert core.browser_test_runs(snapshot, tmp_path) == []


def test_it_refuses_when_a_port_of_the_test_copy_is_in_use(
    plans: core.Plans, tmp_path: Path, free: list[int], browser: list[core.E2EBrowser]
) -> None:
    free += [9403, 3410]
    procs = [P(5555, 1, "python3 -m http.server 9403", "/tmp", "python3", port=9403)]
    call = ready(plans)
    ctx = Ctx(call, procs)
    assert call.fn(ctx) is False
    assert ctx.lines == [
        CHROMIUM.line,
        "no test copy is running",
        "error: port 9403 is in use: pid 5555, http.server 9403",
        "error: port 3410 is in use: a program this app cannot see",
        "error: the test copy needs ports 9401 to 9410 and 3410 free, and never uses yours; stop "
        "what holds them, then try again",
    ]
    assert ctx.ran == []


def test_it_stops_only_what_an_earlier_check_left_of_its_own(
    plans: core.Plans, tmp_path: Path, free: list[int], browser: list[core.E2EBrowser]
) -> None:
    folder = pid_files(tmp_path, identity=201, rulebook=202, pipeline=203)
    procs = [
        P(201, 1, uvicorn(tmp_path, "identity", 9401), str(tmp_path), "uv"),
        # rulebook.pid's pid now runs the person's own rulebook on 8003: never stopped
        P(202, 1, uvicorn(tmp_path, "rulebook", 8003), str(tmp_path), "uv"),
    ]
    call = ready(plans)
    ctx = Ctx(call, procs)
    assert call.fn(ctx) is True
    assert ctx.ran == [DOWN]
    assert not (folder / "rulebook.pid").exists()
    assert (folder / "identity.pid").exists()  # make web-stack-down stops it
    assert (folder / "pipeline.pid").exists()  # not running: make removes the file
    assert ctx.lines == [
        CHROMIUM.line,
        "left alone: var/web-stack-check/rulebook.pid names pid 202, which runs another program "
        "now: uv run --package compliancewatch-rulebook uvicorn rulebook.main:app -…",
        "ports 9401 to 9410 and 3410 are free",
    ]


def test_the_pid_files_it_never_acts_on(tmp_path: Path) -> None:
    pid_files(tmp_path, identity=201, profile=202, eval=203, pipeline=204, web=205)
    commands = {
        201: uvicorn(tmp_path, "identity", 9401),
        202: uvicorn(tmp_path, "profile", 94020),  # another port: not the test copy's
        203: uvicorn(tmp_path, "eval", 9409),
        205: "node /opt/homebrew/bin/pnpm --filter web dev",
    }
    foreign = core.web_check_pid_files(tmp_path, commands)
    named = [(path.name, pid) for path, pid, _ in foreign]
    assert named == [("profile.pid", 202), ("web.pid", 205)]


def test_with_the_processes_unreadable_it_stops_nothing(
    plans: core.Plans, tmp_path: Path, free: list[int], browser: list[core.E2EBrowser]
) -> None:
    folder = pid_files(tmp_path, identity=201)
    call = ready(plans)
    ctx = Ctx(call, ps_fails=True)
    assert call.fn(ctx) is False
    assert ctx.ran == []
    assert (folder / "identity.pid").exists()
    assert ctx.lines[-1].startswith("error: the processes could not be read")


def test_the_browser_tests_check_their_port_again_and_note_when_they_begin(
    plans: core.Plans, free: list[int]
) -> None:
    click = steps(plans)["build the web app and click through it in a robot browser"]
    assert click.commands == (E2E,)
    assert click.interrupt
    free.append(3410)
    ctx = Ctx(click)
    run = core.WebCheckRun()
    assert plans._web_check_click(ctx, run) is False
    assert ctx.lines == ["error: port 3410 is in use: something started there"]
    assert ctx.ran == []
    assert run.began is None
    free.clear()
    before = time.time()
    assert plans._web_check_click(ctx, run) is True
    assert ctx.ran == [E2E]
    assert ctx.envs == [()]  # Playwright's own Chromium: nothing to name
    assert run.began is not None
    assert before <= run.began <= time.time()


def web_app(repo: Path, etime: str) -> list[P]:
    web = str(repo / "apps" / "web")
    return [
        P(300, 1, "/bin/sh -c pnpm start", web, "sh"),
        P(301, 300, "node /opt/homebrew/bin/pnpm start", web, "node"),
        P(302, 301, f"node {web}/node_modules/.bin/../next/dist/bin/next start", web, "node"),
        P(303, 302, "next-server (v16.3.8)", web, "next-server", etime, port=3410),
    ]


def test_the_clean_up_stops_the_test_copy_and_the_web_app_the_browser_tests_left(
    plans: core.Plans, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_files(tmp_path, identity=201)
    stopped: list[tuple[tuple[int, ...], dict[int, str]]] = []

    def stop_named(
        reach: Sequence[int], named: Mapping[int, str], *args: object, **kwargs: object
    ) -> core.StopResult:
        stopped.append((tuple(reach), dict(named)))
        return core.StopResult(tuple(reach))

    monkeypatch.setattr(core, "stop_named", stop_named)
    procs = [P(201, 1, uvicorn(tmp_path, "identity", 9401), str(tmp_path), "uv")]
    procs += web_app(tmp_path, "01:00")
    stop = steps(plans)["stop the test copy"]
    assert stop.always
    assert stop.commands == (*core.scan_commands(), DOWN)
    ctx = Ctx(stop, procs)
    # the browser tests began ten minutes ago: the next start of a minute ago is theirs
    assert plans._web_check_stop(ctx, core.WebCheckRun(began=time.time() - 600)) is True
    assert ctx.ran == [DOWN]
    assert "the browser tests left their web app on port 3410" in ctx.lines
    # the tree from the top of the web app's own chain, next start and next-server, never the
    # pnpm or the shell Playwright started it with
    assert [reach for reach, _ in stopped] == [(302, 303)]
    assert stopped[0][1][303] == "next-server (v16.3.8)"


def test_the_clean_up_leaves_alone_a_web_app_older_than_the_browser_tests(
    plans: core.Plans, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[object] = []
    monkeypatch.setattr(core, "stop_named", lambda *args, **kwargs: called.append(args))
    snapshot_ctx = Ctx(steps(plans)["stop the test copy"], web_app(tmp_path, "01:00"))
    snapshot = core.probe_processes(tmp_path, {}, plans.manager.registry, snapshot_ctx.capture)
    target, why = core.web_check_web_app(snapshot, time.time() - 30)
    assert target is None
    assert why == "port 3410 is held by pid 303, which started before the browser tests; left alone"
    target, why = core.web_check_web_app(snapshot, time.time() - 600)
    assert target is not None
    assert target.pids == (302, 303)
    assert why == ""
    # a listener that is not this checkout's web app is never the check's
    other = [P(600, 1, "python3 -m http.server 3410", "/tmp", "python3", port=3410)]
    ctx = Ctx(steps(plans)["stop the test copy"], other)
    snapshot = core.probe_processes(tmp_path, {}, plans.manager.registry, ctx.capture)
    target, why = core.web_check_web_app(snapshot, time.time() - 600)
    assert target is None
    assert why == "port 3410 is held by pid 600, not the check's web app; left alone"
    assert called == []


def test_the_clean_up_without_browser_tests_reads_no_web_app(
    plans: core.Plans, tmp_path: Path
) -> None:
    stop = steps(plans)["stop the test copy"]
    ctx = Ctx(stop)
    assert stop.fn(ctx) is True
    assert ctx.lines == ["no test copy is running"]
    assert ctx.ran == []
    assert ctx.read == []


def test_it_refuses_when_there_is_no_browser_for_the_tests(
    plans: core.Plans, tmp_path: Path, free: list[int], browser: list[core.E2EBrowser]
) -> None:
    folder = pid_files(tmp_path, identity=201)
    browser[0] = core.E2EBrowser(None, "error: there is no browser for the tests: none here")
    call = ready(plans)
    ctx = Ctx(call, [P(201, 1, uvicorn(tmp_path, "identity", 9401), str(tmp_path), "uv")])
    assert call.fn(ctx) is False
    assert ctx.lines == ["error: there is no browser for the tests: none here"]
    assert ctx.ran == []  # nothing stopped, nothing started
    assert (folder / "identity.pid").exists()


def test_the_browser_tests_drive_the_browser_the_first_step_chose(
    plans: core.Plans, free: list[int], browser: list[core.E2EBrowser]
) -> None:
    chrome = "Playwright's own Chromium is not downloaded here, so the browser tests use Chrome"
    browser[0] = core.E2EBrowser("chrome", chrome)
    by_label = steps(plans)
    run = core.WebCheckRun()
    first = Ctx(by_label["check that the test copy can start"])
    assert plans._web_check_ready(first, run) is True
    assert first.lines[0] == chrome
    assert run.channel == "chrome"
    click = Ctx(by_label["build the web app and click through it in a robot browser"])
    assert plans._web_check_click(click, run) is True
    assert click.envs == [(("CW_E2E_BROWSER_CHANNEL", "chrome"),)]


# ---- which browser: playwright-core's browsers.json and the folder Playwright downloads into ----


def fake_playwright(repo: Path, revision: str = "1243") -> Path:
    """The web app's Playwright as pnpm lays it out: apps/web links @playwright/test, which links
    playwright beside it, which links playwright-core beside it. Its playwright-core folder."""
    pnpm = repo / "node_modules" / ".pnpm"
    test = pnpm / "@playwright+test@1.63.0" / "node_modules" / "@playwright" / "test"
    runner = pnpm / "playwright@1.63.0" / "node_modules" / "playwright"
    core_dir = pnpm / "playwright-core@1.63.0" / "node_modules" / "playwright-core"
    for folder in (test, runner, core_dir):
        folder.mkdir(parents=True)
        (folder / "package.json").write_text("{}")
    listing = [{"name": "chromium", "revision": revision}]
    listing.append({"name": "chromium-headless-shell", "revision": revision})
    (core_dir / "browsers.json").write_text(json.dumps({"browsers": listing}))
    web = repo / "apps" / "web" / "node_modules" / "@playwright"
    web.mkdir(parents=True)
    os.symlink(test, web / "test")
    os.symlink(runner, test.parent.parent / "playwright")
    os.symlink(core_dir, runner.parent / "playwright-core")
    return core_dir.resolve()


def headless_shell(browsers: Path, host: str = "mac-arm64", revision: str = "1243") -> None:
    program = browsers / f"chromium_headless_shell-{revision}" / f"chrome-headless-shell-{host}"
    program.mkdir(parents=True)
    (program / "chrome-headless-shell").write_text("")


def choose(repo: Path, settings: dict[str, str] | None = None, **mac: object) -> core.E2EBrowser:
    """e2e_browser on a made-up Mac: an arm64 one with its home in the repo and no Chrome."""
    here: dict[str, object] = {
        "home": repo / "home",
        "system": "darwin",
        "machine": "arm64",
        "chrome": str(repo / "no-chrome"),
    }
    here.update(mac)
    return core.e2e_browser(repo, settings or {}, **here)  # type: ignore[arg-type]


def test_it_finds_the_web_app_s_playwright_core_as_node_does(tmp_path: Path) -> None:
    core_dir = fake_playwright(tmp_path)
    assert core.playwright_core(tmp_path) == core_dir
    assert core.playwright_core(tmp_path / "elsewhere") is None


def test_playwright_s_own_chromium_when_it_is_downloaded(tmp_path: Path) -> None:
    fake_playwright(tmp_path)
    headless_shell(tmp_path / "home" / "Library" / "Caches" / "ms-playwright")
    chosen = choose(tmp_path, chrome=str(tmp_path / "chrome"))
    assert chosen == CHROMIUM  # as on CI, even with Chrome installed


def test_google_chrome_when_playwright_s_chromium_is_missing(tmp_path: Path) -> None:
    fake_playwright(tmp_path)
    # another revision's download is not this Playwright's
    headless_shell(tmp_path / "home" / "Library" / "Caches" / "ms-playwright", revision="1200")
    (tmp_path / "chrome").write_text("")
    chosen = choose(tmp_path, chrome=str(tmp_path / "chrome"))
    assert chosen.channel == "chrome"
    assert chosen.line == (
        "Playwright's own Chromium is not downloaded here, so the browser tests use your "
        "installed Google Chrome"
    )
    # Playwright's channel chrome is Google Chrome at its one place on a Mac
    assert core.CHROME_PROGRAMS["darwin"] == (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )


def test_no_browser_at_all_says_what_to_do(tmp_path: Path) -> None:
    fake_playwright(tmp_path)
    chosen = choose(tmp_path)
    assert chosen.channel is None
    assert chosen.line.startswith("error: there is no browser for the tests: ")
    assert "Download the test browser (make web-e2e-install, about 150 MB)" in chosen.line


def test_a_host_s_own_download_counts(tmp_path: Path) -> None:
    fake_playwright(tmp_path)
    headless_shell(tmp_path / "home" / "Library" / "Caches" / "ms-playwright", host="mac-x64")
    assert choose(tmp_path, machine="x86_64") == CHROMIUM
    assert choose(tmp_path).channel is None  # an arm64 Mac needs its own build
    cache = tmp_path / "xdg"
    headless_shell(cache / "ms-playwright", host="linux64")
    linux = choose(tmp_path, {"XDG_CACHE_HOME": str(cache)}, system="linux", machine="x86_64")
    assert linux == CHROMIUM


def test_playwright_s_browsers_path_is_followed(tmp_path: Path) -> None:
    core_dir = fake_playwright(tmp_path)
    headless_shell(core_dir / ".local-browsers")
    assert choose(tmp_path, {"PLAYWRIGHT_BROWSERS_PATH": "0"}) == CHROMIUM
    assert choose(tmp_path).channel is None
    headless_shell(tmp_path / "browsers")
    assert choose(tmp_path, {"PLAYWRIGHT_BROWSERS_PATH": "browsers"}) == CHROMIUM
    absolute = {"PLAYWRIGHT_BROWSERS_PATH": str(tmp_path / "browsers")}
    assert choose(tmp_path, absolute) == CHROMIUM


def test_a_channel_already_named_is_kept(tmp_path: Path) -> None:
    chosen = choose(tmp_path, {"CW_E2E_BROWSER_CHANNEL": "msedge"})
    assert chosen.channel == "msedge"
    assert chosen.line == "the browser tests use the browser CW_E2E_BROWSER_CHANNEL names: msedge"


def test_without_the_web_app_s_packages_it_says_so(tmp_path: Path) -> None:
    chosen = choose(tmp_path)
    assert chosen.channel is None
    assert chosen.line.startswith("error: the web app's Playwright is not installed")


def test_when_browsers_json_says_nothing_the_tests_try_playwright_s_chromium(
    tmp_path: Path,
) -> None:
    core_dir = fake_playwright(tmp_path)
    (core_dir / "browsers.json").write_text("not json")
    chosen = choose(tmp_path)
    assert chosen.channel == ""
    assert "cannot tell" in chosen.line
