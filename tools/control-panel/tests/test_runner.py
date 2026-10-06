"""The runner streams a plan's lines, stops at the first failure unless told to keep going, refuses
what the rules forbid wherever a program starts, and cancels the running step's whole process
group; the registry and the background manager keep what the panel started. The programs here are
short Python scripts: no Docker, no network."""

import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import panel_core as core
import pytest

PY = sys.executable


class Events:
    def __init__(self) -> None:
        self.items: list[core.RunnerEvent] = []
        self.done = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, event: core.RunnerEvent) -> None:
        with self._lock:
            self.items.append(event)
        if isinstance(event, core.End):
            self.done.set()

    def lines(self) -> list[str]:
        with self._lock:
            return [event.text for event in self.items if isinstance(event, core.Line)]

    def end(self) -> core.End:
        ends = [event for event in self.items if isinstance(event, core.End)]
        assert len(ends) == 1
        return ends[0]


def wait_for(predicate: Callable[[], bool], seconds: float = 15.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


def runner(
    tmp_path: Path,
    registry: core.Registry | None = None,
    timeout: float | None = None,
    known: dict[str, str] | None = None,
) -> tuple[core.Runner, Events]:
    events = Events()
    made = core.Runner("steps", tmp_path, core.program_env(), events, registry, timeout, known)
    return made, events


def run(
    tmp_path: Path,
    plan: core.Plan,
    registry: core.Registry | None = None,
    timeout: float | None = None,
) -> Events:
    made, events = runner(tmp_path, registry, timeout)
    assert made.start(plan)
    assert events.done.wait(30)
    wait_for(lambda: not made.busy)
    return events


def python(label: str, code: str) -> core.Cmd:
    return core.Cmd(label, (PY, "-c", code))


def writes(path: Path) -> str:
    return f"open({str(path)!r}, 'w').close()"


def test_a_plan_streams_its_lines_and_ends_done(tmp_path: Path) -> None:
    plan = core.Plan(
        "hello", (python("say hello", "print('hello'); print('\\x1b[31mred\\x1b[0m')"),)
    )
    events = run(tmp_path, plan)
    lines = events.lines()
    assert lines[:3] == ["\n▸ say hello", "hello", "red"]
    assert lines[-1] == "✓ hello done"
    end = events.end()
    assert end.ok
    assert not end.cancelled
    assert [(result.label, result.state) for result in end.results] == [("say hello", "ok")]


def test_the_programs_get_the_panel_s_environment(tmp_path: Path) -> None:
    code = "import os; print(os.environ['CW_PIPELINE_CRAWL_ENABLED'], 'ARGS' in os.environ)"
    events = run(tmp_path, core.Plan("env", (python("env", code),)))
    assert "false False" in events.lines()


def test_a_failed_step_stops_the_plan(tmp_path: Path) -> None:
    plan = core.Plan(
        "two steps",
        (python("fail", "raise SystemExit(3)"), python("never", "print('never')")),
    )
    events = run(tmp_path, plan)
    assert "never" not in events.lines()
    stopped = [line for line in events.lines() if line.startswith("✗ fail failed after")]
    assert stopped
    assert stopped[0].endswith("stopped here")
    end = events.end()
    assert not end.ok
    assert [result.state for result in end.results] == ["failed", "skipped"]


def test_keep_going_runs_every_step_and_sums_them_up(tmp_path: Path) -> None:
    plan = core.Plan(
        "gates",
        (python("first", "raise SystemExit(1)"), python("second", "print('ran')")),
        keep_going=True,
        gates=True,
    )
    events = run(tmp_path, plan)
    lines = events.lines()
    assert "ran" in lines
    assert any(line.startswith("\ngates: 1 of 2 passed in") for line in lines)
    assert any(line.startswith("  ✗ first") for line in lines)
    assert any(line.startswith("  ✓ second") for line in lines)
    updates = [e for e in events.items if isinstance(e, core.StepUpdate) and e.state != "running"]
    assert [(u.label, u.state) for u in updates] == [("first", "failed"), ("second", "ok")]


def test_a_missing_program_or_a_broken_step_fails_without_leaving_the_runner_busy(
    tmp_path: Path,
) -> None:
    def broken(ctx: core.StepContext) -> bool:
        raise RuntimeError("a defect")

    events = run(tmp_path, core.Plan("missing", (core.Cmd("x", ("cw-no-such-program",)),)))
    assert any(line.startswith("error: cannot run cw-no-such-program") for line in events.lines())
    events = run(tmp_path, core.Plan("broken", (core.Call("broken", broken),)))
    assert "error: broken: RuntimeError('a defect')" in events.lines()
    assert not events.end().ok


def test_start_refuses_a_plan_that_breaks_a_rule(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    made, events = runner(tmp_path)
    plan = core.Plan("x", (core.Cmd("x", (PY, "-c", writes(marker), "--destructive")),))
    assert not made.start(plan)
    assert not made.busy
    assert events.lines() == ["error: refused: x: passes --destructive"]
    unknown = core.Plan("y", (core.make("backfill"),))
    made, events = runner(tmp_path, known={"dev": ""})
    assert not made.start(unknown)
    assert events.lines() == [
        "error: refused: make backfill: make backfill is never run here",
        "error: refused: make backfill: make backfill is not a target of this checkout's Makefile",
    ]
    assert not marker.exists()


def test_execute_checks_the_program_and_its_whole_environment_whoever_asks(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "ran"
    made, events = runner(tmp_path)
    assert not made.execute("x", (PY, "-c", writes(marker), "--destructive"))
    assert not made.execute("y", (PY, "-c", writes(marker)), (("ARGS", "--json"),))
    assert not made.execute("z", (PY, "-c", writes(marker)), (("CW_PIPELINE_CRAWL_ENABLED", "1"),))
    assert not marker.exists()
    assert events.lines() == [
        "error: refused: x: passes --destructive",
        "error: refused: y: carries ARGS, which make would read",
        "error: refused: z: does not keep the crawl off (CW_PIPELINE_CRAWL_ENABLED=false)",
    ]
    assert made.execute("ok", (PY, "-c", writes(marker)))
    assert marker.exists()


def test_a_call_runs_only_the_programs_it_declares(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    declared = (PY, "-c", "print('from its program')")

    def step(ctx: core.StepContext) -> bool:
        ctx.log("from the call", "ok")
        code, out, _ = ctx.capture(declared, cwd=tmp_path, env=core.program_env(), timeout=10)
        assert (code, out) == (0, "from its program\n")
        return ctx.run(declared) and ctx.wait(0.01)

    events = run(tmp_path, core.Plan("call", (core.Call("call", step, (declared,)),)))
    assert events.lines()[1:3] == ["from the call", "from its program"]
    assert events.end().ok

    def sneaky(ctx: core.StepContext) -> bool:
        code, _, err = ctx.capture((PY, "-c", writes(marker)), cwd=tmp_path, env={}, timeout=5)
        assert code is None
        assert "does not declare" in err
        return ctx.run((PY, "-c", writes(marker)))

    events = run(tmp_path, core.Plan("sneaky", (core.Call("sneaky", sneaky, (declared,)),)))
    assert not events.end().ok
    assert not marker.exists()
    refusals = [line for line in events.lines() if line.startswith("error: refused")]
    assert len(refusals) == 2
    assert refusals[0].startswith("error: refused: sneaky does not declare ")


SPAWN = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "print(child.pid, flush=True)\n"
    "time.sleep(60)\n"
)
STUBBORN = (
    "import subprocess, sys, time\n"
    "code = 'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "print(1, flush=True); time.sleep(60)'\n"
    "child = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE)\n"
    "child.stdout.readline()\n"
    "print(child.pid, flush=True)\n"
    "time.sleep(60)\n"
)


def zombie(pid: int) -> bool:
    status = Path(f"/proc/{pid}/status")
    try:
        return "zombie" in status.read_text()
    except OSError:
        return False


def gone(pid: int) -> bool:
    return not core.pid_alive(pid) or zombie(pid)


def child_of(events: Events) -> int:
    wait_for(lambda: any(line.isdigit() for line in events.lines()))
    return int(next(line for line in events.lines() if line.isdigit()))


def test_cancel_ends_the_step_s_whole_process_group(tmp_path: Path) -> None:
    plan = core.Plan("long", (python("sleep", SPAWN), python("after", "print('after')")))
    made, events = runner(tmp_path)
    assert made.start(plan)
    child = child_of(events)
    assert core.pid_alive(child)
    assert made.cancel()
    assert events.done.wait(15)
    end = events.end()
    assert end.cancelled
    assert not end.ok
    assert [result.state for result in end.results] == ["cancelled", "cancelled"]
    assert "■ long cancelled" in events.lines()
    wait_for(lambda: gone(child))
    assert not made.busy
    assert not made.cancel()


def test_cancel_kills_what_of_the_group_outlives_sigterm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core, "KILL_GRACE_SECONDS", 0.5)
    made, events = runner(tmp_path)
    assert made.start(core.Plan("stubborn", (python("stubborn", STUBBORN),)))
    child = child_of(events)
    assert made.cancel()
    assert events.done.wait(15)
    # The step's first process died of SIGTERM; its child ignored it and gets SIGKILL
    wait_for(lambda: gone(child), seconds=10)


def test_a_step_that_overruns_its_time_is_stopped(tmp_path: Path) -> None:
    plan = core.Plan("slow", (python("sleep", "import time; time.sleep(30)"),))
    events = run(tmp_path, plan, timeout=1)
    assert "error: still running after 1 s; stopped" in events.lines()
    assert not events.end().ok


def test_the_registry_records_each_step_s_group_and_forgets_dead_ones(tmp_path: Path) -> None:
    registry = core.Registry(tmp_path / "var" / "control-panel")
    registry.prune({1})
    assert not registry.path.exists()
    run(tmp_path, core.Plan("hello", (python("say hello", "print('hi')"),)), registry=registry)
    groups = registry.groups()
    assert list(groups.values()) == ["say hello"]
    registry.prune(set(groups))
    assert registry.groups() == groups
    registry.prune(set())
    assert registry.groups() == {}
    registry.path.write_text("{not json")
    assert registry.groups() == {}


def spec(
    tmp_path: Path, code: str, env: tuple[tuple[str, str], ...] = core.NO_CRAWL
) -> core.Background:
    panel = tmp_path / "var" / "control-panel"
    return core.Background(
        "worker-demo",
        "demo worker",
        (PY, "-c", code),
        env,
        panel / "worker-demo.pid",
        panel / "worker-demo.log",
        "time.sleep",
    )


def manager(tmp_path: Path) -> core.BackgroundManager:
    registry = core.Registry(tmp_path / "var" / "control-panel")
    return core.BackgroundManager(tmp_path, core.program_env(), registry)


def ps_says(commands: Mapping[int, str]) -> core.Capture:
    """A capture that answers ps with these command lines (in PS_ARGV's columns)."""

    def capture(
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        stdin_path: Path | None = None,
    ) -> tuple[int | None, str, str]:
        assert tuple(argv) == core.PS_ARGV
        rows = "".join(f"{pid} 1 {pid} 00:01 {command}\n" for pid, command in commands.items())
        return 0, rows, ""

    return capture


WORKER = (
    "import os, time; print(os.environ['CW_PIPELINE_CRAWL_ENABLED'], flush=True); time.sleep(60)"
)


def test_a_background_process_starts_in_its_own_session_and_stops(tmp_path: Path) -> None:
    keeper = manager(tmp_path)
    lines: list[str] = []
    demo = spec(tmp_path, WORKER)
    pid = keeper.start(demo, lambda text, tag: lines.append(text))
    assert pid is not None
    assert lines == [f"demo worker started (pid {pid}, log var/control-panel/worker-demo.log)"]
    assert demo.pid_file.read_text() == f"{pid}\n"
    assert os.getpgid(pid) == pid
    assert keeper.live_pid(demo) == pid
    assert pid in keeper.registry.groups()
    assert keeper.start(demo, lambda text, tag: lines.append(text)) == pid
    wait_for(lambda: "false" in demo.log_file.read_text())
    assert keeper.stop(demo, lambda text, tag: lines.append(text), grace=5)
    assert lines[-1] == f"demo worker stopped (pid {pid})"
    assert keeper.live_pid(demo) is None
    assert not demo.pid_file.exists()
    assert keeper.stop(demo, lambda text, tag: lines.append(text))
    assert lines[-1] == "demo worker is not running"


def test_a_background_start_that_breaks_a_rule_starts_nothing(tmp_path: Path) -> None:
    lines: list[str] = []
    crawl = spec(tmp_path, "import time; time.sleep(60)", (("CW_PIPELINE_CRAWL_ENABLED", "true"),))
    assert manager(tmp_path).start(crawl, lambda text, tag: lines.append(text)) is None
    assert lines == [
        "error: demo worker refused: does not keep the crawl off (CW_PIPELINE_CRAWL_ENABLED=false)"
    ]
    assert not crawl.pid_file.exists()
    assert not crawl.log_file.exists()


def test_a_recycled_pid_neither_reads_as_running_nor_blocks_a_start(tmp_path: Path) -> None:
    demo = spec(tmp_path, "import time; time.sleep(60)")
    demo.pid_file.parent.mkdir(parents=True)
    # An earlier window recorded this test's own pid: alive, but it runs pytest, not the worker
    demo.pid_file.write_text(f"{os.getpid()}\n")
    later = manager(tmp_path)
    recycled = ps_says({os.getpid(): f"{PY} -m pytest"})
    assert later.live_pid(demo, recycled) is None
    assert later.states([demo], recycled) == {"worker-demo": None}
    running = ps_says({os.getpid(): f"{PY} -c import time; time.sleep(60)"})
    assert later.live_pid(demo, running) == os.getpid()
    lines: list[str] = []
    pid = later.start(demo, lambda text, tag: lines.append(text), recycled)
    try:
        assert pid is not None
        assert pid != os.getpid()
        assert demo.pid_file.read_text() == f"{pid}\n"
    finally:
        if pid is not None:
            os.killpg(pid, signal.SIGKILL)


def test_a_stale_pid_file_is_removed_and_its_pid_left_alone(tmp_path: Path) -> None:
    first = manager(tmp_path)
    demo = spec(tmp_path, "import time; time.sleep(60)")
    lines: list[str] = []
    pid = first.start(demo, lambda text, tag: lines.append(text))
    assert pid is not None
    try:
        # A later window finds the pid running another program: the file is stale
        later = manager(tmp_path)
        other = ps_says({pid: "/usr/bin/some-other-program"})
        assert later.stop(demo, lambda text, tag: lines.append(text), capture=other)
        assert lines[-1] == (
            f"demo worker is not running: pid {pid} of its pid file runs another program"
        )
        assert not demo.pid_file.exists()
        assert core.pid_alive(pid)
    finally:
        os.killpg(pid, signal.SIGKILL)


def test_a_dump_is_read_with_pg_restore_list_on_its_standard_input(tmp_path: Path) -> None:
    dump = tmp_path / "var" / "backups" / "20261006T101500Z.dump"
    dump.parent.mkdir(parents=True)
    dump.write_bytes(b"PGDMP")
    seen: list[tuple[tuple[str, ...], Path | None]] = []

    def pg_restore(code: int, out: str, err: str) -> core.Capture:
        def capture(
            argv: Sequence[str],
            *,
            cwd: Path,
            env: Mapping[str, str],
            timeout: float,
            stdin_path: Path | None = None,
        ) -> tuple[int | None, str, str]:
            seen.append((tuple(argv), stdin_path))
            return code, out, err

        return capture

    listing = ";\n; Archive created at 2026-10-06 10:15:00 IST\n;\n3456; 0 0 ENCODING - ENCODING\n"
    relative = "var/backups/20261006T101500Z.dump"
    ok = core.check_dump(tmp_path, {}, relative, pg_restore(0, listing, ""))
    assert ok == (True, f"pg_restore --list reads 1 entries from {relative}")
    assert seen == [(core.PG_RESTORE_LIST, dump)]
    short = "pg_restore: error: could not read from input file: end of file\n"
    bad = core.check_dump(tmp_path, {}, relative, pg_restore(1, "", short))
    assert bad == (
        False,
        f"{relative} is not a dump pg_restore can read: "
        "pg_restore: error: could not read from input file: end of file",
    )


def test_the_rate_limit_lets_one_read_through_every_thirty_seconds() -> None:
    now = [100.0]
    limit = core.RateLimit(30, clock=lambda: now[0])
    assert limit.wait() == 0
    now[0] = 112
    assert limit.wait() == 18
    now[0] = 130
    assert limit.wait() == 0
    assert limit.wait() == 30


def test_every_other_way_a_program_starts_is_checked_too(tmp_path: Path) -> None:
    env = core.program_env()
    assert core.run_capture(("bash", "-c", "echo hi"), cwd=tmp_path, env=env, timeout=5) == (
        None,
        "",
        "refused: runs bash",
    )
    with pytest.raises(core.RefusedError, match="runs zsh"):
        core.spawn_detached(("zsh", "-c", "open ."), env)
    bare = {key: value for key, value in env.items() if key != "CW_PIPELINE_CRAWL_ENABLED"}
    with pytest.raises(core.RefusedError, match="does not keep the crawl off"):
        core.open_path(tmp_path, bare)
    with pytest.raises(core.RefusedError, match="carries ARGS"):
        core.open_psql_terminal(tmp_path, {**env, "ARGS": "x"})
    assert not (tmp_path / "var").exists()


def test_a_destructive_target_runs_only_inside_a_plan_that_asked_first(tmp_path: Path) -> None:
    made, events = runner(tmp_path)
    assert not made.execute("reset", ("make", "dev-reset"))
    assert events.lines() == ["error: refused: reset: a destructive target without a confirm"]
