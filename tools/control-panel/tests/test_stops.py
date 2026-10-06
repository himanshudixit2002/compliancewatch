"""A stop signals what its question named and nothing else: a fresh scan decides what still
runs, one os.kill per pid (never a process group), SIGKILL only to what still runs the same
program, and a step that met something new fails, naming it, instead of reporting success.
Processes an editor or an agent runs are never the checkout's to stop."""

import signal
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import panel_core as core
import panel_demo as demo
import panel_server as server
import pytest

REPO = Path("/Users/dev/cw")
SELF = 90000
PYTEST = "/Users/dev/cw/.venv/bin/python -m pytest -n 2"
WORKER = "/Users/dev/cw/.venv/bin/python -m xdist.worker"


def proc(pid: int, ppid: int, pgid: int, command: str) -> core.Proc:
    return core.Proc(pid, ppid, pgid, 60, command)


def snapshot(
    procs: Mapping[int, core.Proc],
    project: set[int] | None = None,
    guarded: set[int] | None = None,
    origins: Mapping[int, str] | None = None,
) -> core.ProcessSnapshot:
    every = dict(procs)
    every.setdefault(
        SELF, proc(SELF, 1, SELF, ".venv/bin/python tools/control-panel/panel_server.py")
    )
    return core.ProcessSnapshot(
        every,
        {},
        frozenset(project if project is not None else set(procs)),
        dict(origins or dict.fromkeys(procs, "other")),
        (),
        SELF,
        0.0,
        "",
        frozenset(guarded or set()),
    )


class Kills:
    """os.kill for the tests: records each signal; a SIGTERMed or SIGKILLed pid is gone, unless
    it is ``stubborn``."""

    def __init__(self, stubborn: set[int] | None = None) -> None:
        self.sent: list[tuple[int, int]] = []
        self.stubborn = stubborn or set()
        self.gone: set[int] = set()

    def __call__(self, pid: int, sig: int) -> None:
        self.sent.append((pid, sig))
        if pid not in self.stubborn or sig == signal.SIGKILL:
            self.gone.add(pid)

    def alive(self, pid: int) -> bool:
        return pid not in self.gone


def run(
    reach: list[int],
    named: Mapping[int, str],
    state: core.ProcessSnapshot,
    kills: Kills,
    commands_now: Callable[[], Mapping[int, str]] | None = None,
) -> tuple[core.StopResult | None, list[str]]:
    lines: list[str] = []
    result = core.stop_named(
        reach,
        named,
        state,
        REPO,
        lambda text, tag: lines.append(text),
        lambda seconds: True,
        commands_now or (lambda: {pid: p.command for pid, p in state.procs.items()}),
        kill=kills,
        alive=kills.alive,
        grace=1.0,
    )
    return result, lines


def test_pytest_workers_that_joined_the_group_after_the_question_are_left_alone() -> None:
    # The question named make check's pytest (500) and its first worker (501); two more workers
    # (502, 503) joined process group 500 before the stop ran.
    procs = {
        500: proc(500, 1, 500, PYTEST),
        501: proc(501, 500, 500, WORKER),
        502: proc(502, 500, 500, WORKER),
        503: proc(503, 500, 500, WORKER),
    }
    state = snapshot(procs)
    named = {500: PYTEST, 501: WORKER}
    kills = Kills()
    result, lines = run([500, 501, 502, 503], named, state, kills)
    assert result is not None
    assert kills.sent == [(501, signal.SIGTERM), (500, signal.SIGTERM)]  # one kill per pid
    assert result.signalled == (500, 501)
    assert result.new == (502, 503)
    assert "left alone, started after the question: pid 502 xdist.worker" in lines
    assert any(line.startswith("left alone, started after the question: pid 503") for line in lines)
    assert core.changed_line(result) == (
        "error: changed since the question: 2 processes started after it; they were left "
        "alone. Ask again to see what runs now."
    )


def test_a_pid_that_runs_another_program_now_is_left_alone() -> None:
    procs = {500: proc(500, 1, 500, "/usr/bin/vim notes.txt"), 501: proc(501, 500, 500, WORKER)}
    kills = Kills()
    result, lines = run([500, 501], {500: PYTEST, 501: WORKER}, snapshot(procs), kills)
    assert result is not None
    assert kills.sent == [(501, signal.SIGTERM)]
    assert result.changed == (500,)
    assert "left alone, runs another program now: pid 500 vim notes.txt" in lines


def test_sigkill_goes_only_to_what_still_runs_the_named_program() -> None:
    procs = {500: proc(500, 1, 500, PYTEST), 501: proc(501, 500, 500, WORKER)}
    kills = Kills(stubborn={500, 501})
    # by the time of the SIGKILL, 501's pid runs something else
    result, lines = run(
        [500, 501],
        {500: PYTEST, 501: WORKER},
        snapshot(procs),
        kills,
        commands_now=lambda: {500: PYTEST, 501: "/bin/sleep 100"},
    )
    assert result is not None
    assert kills.sent == [
        (501, signal.SIGTERM),
        (500, signal.SIGTERM),
        (500, signal.SIGKILL),
    ]
    assert lines[-1] == "still running after 1 s, sent SIGKILL: 500"


def test_a_cancel_while_waiting_stops_the_step() -> None:
    procs = {500: proc(500, 1, 500, PYTEST)}
    kills = Kills(stubborn={500})
    result = core.stop_named(
        [500],
        {500: PYTEST},
        snapshot(procs),
        REPO,
        lambda text, tag: None,
        lambda seconds: False,
        dict,
        kill=kills,
        alive=kills.alive,
    )
    assert result is None
    assert kills.sent == [(500, signal.SIGTERM)]


def test_a_stop_never_falls_back_from_one_mode_to_the_other() -> None:
    procs = {
        500: proc(500, 1, 500, PYTEST),
        501: proc(501, 500, 500, WORKER),
        700: proc(700, 1, 500, "/usr/bin/caffeinate"),  # in the group, not the checkout's
    }
    state = snapshot(procs, project={500, 501})
    group = core.stop_reach(500, "group", state)
    assert group.refused == "its process group may not be signalled whole now"
    assert core.stop_reach(500, "tree", state) == core.StopTarget("tree", 500, (500, 501))


def test_the_stop_step_signals_only_the_named_pids_and_fails_on_new_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    procs = {
        500: proc(500, 1, 500, PYTEST),
        501: proc(501, 500, 500, WORKER),
        502: proc(502, 500, 500, WORKER),
        503: proc(503, 500, 500, WORKER),
    }
    state = snapshot(procs)
    kills = Kills()
    monkeypatch.setattr(core, "probe_processes", lambda *args, **kwargs: state)
    monkeypatch.setattr(core.os, "kill", kills)
    monkeypatch.setattr(core, "pid_alive", kills.alive)
    monkeypatch.setattr(core, "process_commands", lambda *args, **kwargs: {})
    plans = core.Plans(
        core.Project(
            repo=tmp_path,
            env=core.program_env({"PATH": "/usr/bin"}),
            ports=core.resolve_ports({}, {}),
            make_targets={},
            checks=[],
            check_steps=[],
            screens=[],
            workers=[],
            relays=[],
        ),
        core.BackgroundManager(tmp_path, {}, core.Registry(tmp_path / "registry")),
    )
    plan = plans.stop_process(500, PYTEST, "group", {500: PYTEST, 501: WORKER})
    step = plan.steps[0]
    assert isinstance(step, core.Call)
    lines: list[str] = []

    class Ctx:
        def log(self, text: str, tag: str | None = None) -> None:
            lines.append(text)

        def wait(self, seconds: float) -> bool:
            return True

        def capture(self, *args: object, **kwargs: object) -> tuple[int, str, str]:
            return 0, "", ""

    assert step.fn(Ctx()) is False  # type: ignore[arg-type]
    assert kills.sent == [(501, signal.SIGTERM), (500, signal.SIGTERM)]
    assert lines[-1].startswith("error: changed since the question: 2 processes started after it")


def test_what_an_editor_or_an_agent_runs_is_guarded() -> None:
    procs = {
        6841: proc(6841, 1, 6841, "/Applications/Claude.app/Contents/Helpers/disclaimer -- claude"),
        6842: proc(6842, 6841, 6841, "/Users/dev/.local/bin/claude --add-dir /Users/dev/cw"),
        6900: proc(6900, 6842, 6900, "/bin/bash -c cd /Users/dev/cw && make check"),
        6901: proc(6901, 6900, 6900, "/usr/bin/make check"),
        7000: proc(7000, 1, 7000, "/Applications/Visual Studio Code.app/Contents/MacOS/Electron"),
        7001: proc(7001, 7000, 7000, "/Applications/Visual Studio Code.app/Code Helper (Plugin)"),
        7002: proc(7002, 7001, 7002, "/usr/bin/make test"),
        8000: proc(8000, 1, 8000, "/System/Applications/Utilities/Terminal.app/Terminal"),
        8001: proc(8001, 8000, 8001, "-zsh"),
        8002: proc(8002, 8001, 8002, "/usr/bin/make dev"),
        SELF: proc(SELF, 1, SELF, ".venv/bin/python tools/control-panel/panel_server.py"),
        9100: proc(9100, SELF, 9100, "/usr/bin/make web-stack"),
    }
    assert core.guard_reason(6901, procs, SELF) == "Claude Code"
    assert core.guard_reason(7002, procs, SELF) == "an editor"
    assert core.guard_reason(8002, procs, SELF) == ""  # a person's terminal: theirs to stop
    assert core.guard_reason(9100, procs, SELF) == ""  # what this window started
    project, guarded = core.split_guarded({6901, 7002, 8002, 9100}, procs, SELF)
    assert project == {8002, 9100}
    assert guarded == {6901: "Claude Code", 7002: "an editor"}
    state = snapshot(
        procs,
        project=project,
        guarded=set(guarded),
        origins={6901: "run by Claude Code", 7002: "run by an editor", 8002: "other"},
    )
    assert core.stop_target(6901, state).refused == "Claude Code runs it; stop it there"
    assert core.stop_target(7002, state).refused == "an editor runs it; stop it there"
    assert not core.stop_target(8002, state).refused
    assert set(state.foreign()) == {6901, 7002, 8002}  # still named as other sessions


def test_a_group_with_a_guarded_member_is_never_stopped_whole() -> None:
    procs = {
        500: proc(500, 1, 500, "/usr/bin/make product-check"),
        501: proc(501, 500, 500, PYTEST),
        502: proc(502, 500, 500, "/usr/bin/make check"),
    }
    state = snapshot(procs, project={500, 501}, guarded={502})
    options = core.stop_options(500, state)
    assert [option.mode for option in options] == ["tree"]
    assert options[0].pids == (500, 501)


@pytest.mark.parametrize(
    "command",
    [
        "/Users/dev/cw/.venv/bin/ruff server --preview",
        "/Users/dev/cw/.venv/bin/python -m pylsp",
        "/Users/dev/cw/.venv/bin/dmypy run -- src",
        "/Users/dev/cw/.venv/bin/python -m mypy.dmypy start",
        "node /Users/dev/cw/node_modules/typescript/lib/tsserver.js --useNodeIpc",
        "node /Users/dev/.vscode/extensions/dbaeumer.vscode-eslint/server/out/eslintServer.js",
        "/opt/homebrew/bin/basedpyright-langserver --stdio",
    ],
)
def test_language_servers_are_never_the_checkout_s(command: str) -> None:
    name = Path(command.split()[0]).name
    assert not core.is_project_root(name, command, str(REPO), str(REPO))
    assert core.is_tool_server(command)


# ---- the helper's questions scan afresh -----------------------------------------------------


class Counting(demo.DemoBackend):
    """The demo core, counting its process scans; ``slow`` delays each one."""

    def __init__(self, slow: float = 0.0) -> None:
        super().__init__(pace=0.01)
        self.scans = 0
        self.slow = slow

    def probe_processes(self) -> core.ProcessSnapshot:
        self.scans += 1
        time.sleep(self.slow)
        return super().probe_processes()


def app_over(backend: demo.DemoBackend) -> server.App:
    app = server.App(backend, token="x" * 43, port=1, prefs=server.Prefs(None))
    app.on_probe("status", backend.probe_status())
    return app


def test_a_question_about_processes_scans_afresh() -> None:
    backend = Counting()
    app = app_over(backend)
    app.preview("backup", {"params": {}})  # a safe action asks nothing
    assert backend.scans == 0
    app.preview("databases-stop", {"params": {}})
    assert backend.scans == 1
    app.stop_preview(76165)
    assert backend.scans == 2


def test_a_slow_scan_ends_the_question_instead_of_using_an_old_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "QUESTION_SCAN_SECONDS", 0.05)
    app = app_over(Counting(slow=0.5))
    with pytest.raises(server.ApiError) as caught:
        app.preview("stop-everything", {"params": {}})
    assert caught.value.status == 503
    assert caught.value.code == "scan-slow"


def test_a_process_gone_from_the_fresh_scan_is_not_found() -> None:
    backend = Counting()
    app = app_over(backend)
    app.on_probe("processes", backend.probe_processes())  # the poller saw the web app
    backend.world.web = False  # and it exits before the question
    with pytest.raises(server.ApiError) as caught:
        app.stop_preview(76165)
    assert caught.value.status == 404


def test_the_stop_s_token_carries_the_named_pids_and_programs() -> None:
    backend = Counting()
    app = app_over(backend)
    preview = app.stop_preview(76165)
    seen: dict[str, Any] = {}

    def record(
        pid: int, command: str, mode: str, named: Mapping[int, str] | None = None
    ) -> core.Plan:
        seen.update(pid=pid, mode=mode, named=dict(named or {}))
        return core.Plan("x", (core.Cmd("x", ("true",)),))

    backend.plans.stop_process = record  # type: ignore[method-assign]
    mode = next(option["mode"] for option in preview["options"] if not option["refused"])
    status, _ = app.stop_process(76165, {"mode": mode, "confirm_token": preview["confirm_token"]})
    assert status == 202
    snapshot = backend.probe_processes()
    option = next(o for o in preview["options"] if o["mode"] == mode)
    assert seen["named"] == {p["pid"]: snapshot.procs[p["pid"]].command for p in option["pids"]}


def test_stop_web_app_fails_when_the_web_app_runs_a_process_it_did_not_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    procs = {
        9030: proc(9030, 1, 9030, "node /opt/homebrew/bin/pnpm --filter web dev"),
        9031: proc(9031, 9030, 9030, "node /Users/dev/cw/apps/web/node_modules/.bin/next dev"),
        9032: proc(9032, 9031, 9030, "next-server (v16.3.8)"),
    }
    state = core.ProcessSnapshot(
        {**procs, SELF: proc(SELF, 1, SELF, "panel_server.py")},
        {},
        frozenset(procs),
        dict.fromkeys(procs, "panel web app"),
        (core.Listener(9032, "node", "*", 3000),),
        SELF,
        0.0,
    )
    kills = Kills()
    monkeypatch.setattr(core, "probe_processes", lambda *args, **kwargs: state)
    monkeypatch.setattr(core.os, "kill", kills)
    monkeypatch.setattr(core, "pid_alive", kills.alive)
    monkeypatch.setattr(core, "process_commands", lambda *args, **kwargs: {})
    plans = core.Plans(
        core.Project(
            repo=tmp_path,
            env=core.program_env({"PATH": "/usr/bin"}),
            ports=core.resolve_ports({}, {}),
            make_targets={},
            checks=[],
            check_steps=[],
            screens=[],
            workers=[],
            relays=[],
        ),
        core.BackgroundManager(tmp_path, {}, core.Registry(tmp_path / "registry")),
    )
    # the question named the old next-server; it restarted as 9032 meanwhile
    named = {9030: procs[9030].command, 9031: procs[9031].command, 9029: "next-server (v16.3.8)"}
    call = plans.stop_web_call(named)
    lines: list[str] = []

    class Ctx:
        def log(self, text: str, tag: str | None = None) -> None:
            lines.append(text)

        def wait(self, seconds: float) -> bool:
            return True

        def capture(self, *args: object, **kwargs: object) -> tuple[int, str, str]:
            return 0, "", ""

    assert call.fn(Ctx()) is False  # type: ignore[arg-type]
    assert kills.sent == [(9031, signal.SIGTERM), (9030, signal.SIGTERM)]
    assert "left alone, started after the question: pid 9032 next-server (v16.3.8)" in lines
    assert lines[-1].startswith("error: changed since the question: 1 process started after it")
