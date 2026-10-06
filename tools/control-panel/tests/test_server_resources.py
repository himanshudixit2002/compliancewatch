"""What the helper holds stays bounded and nothing it shows outlives the work: a run whose runner
went idle is finished, a run that cannot start leaves nothing running, the threads stay bounded
after many reconnects and reloads, a window cannot keep the helper from stopping, and Quit stops
it."""

import contextlib
import http.client
import json
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import panel_catalog as catalog
import panel_core as core
import panel_demo as demo
import panel_server as server
import pytest
from serverkit import Served

SCRIPT = Path(server.__file__).resolve()


def wait_for(predicate: Callable[[], bool], seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


def spec(action_id: str = "test-run", kind: str = "step") -> catalog.Spec:
    return catalog.Spec(
        id=action_id,
        title="A test run",
        summary="",
        what_happens=(),
        duration="a moment",
        group="tools",
        safety="safe",
        kind=kind,
    )


def plan() -> core.Plan:
    return core.Plan("A test run", (core.Call("wait", lambda ctx: True),))


class Silent:
    """A runner that says it started and then says nothing: the defect a stale run comes from.
    ``working``: it is busy once started, as a runner at work is."""

    def __init__(self, *, working: bool = False, raises: bool = False) -> None:
        self._busy = False
        self.working = working
        self.raises = raises

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def plan(self) -> core.Plan | None:
        return None

    def start(self, plan: core.Plan) -> bool:
        if self.raises:
            raise RuntimeError("can't start new thread")
        self._busy = self.working
        return True

    def cancel(self) -> bool:
        return False


@pytest.fixture
def served() -> Iterator[Served]:
    with Served() as running:
        running.demo({"speed": 20})
        yield running


def test_a_run_whose_runner_went_idle_is_finished_as_stopped(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "STALE_RUN_SECONDS", 0.3)
    runs = served.app.runs
    runs.runners["steps"] = Silent()
    stream = served.events()
    run = runs.start(spec(), plan(), {})
    assert runs.recent(5)[0]["state"] == "running"  # a runner's last event may still be landing
    wait_for(lambda: runs.recent(5)[0]["state"] != "running")
    shown = runs.recent(5)[0]
    assert shown["state"] == "failed"
    assert shown["error"]["code"] == "stopped"
    assert shown["error"]["message"] == "It stopped unexpectedly"
    assert runs.current("step") is None
    finished = stream.until("run.finished")
    assert finished.data["run_id"] == run.run_id
    assert finished.data["state"] == "failed"
    runs.runners["steps"] = Silent(working=True)
    again = runs.start(spec(), plan(), {})  # nothing is left holding the slot
    time.sleep(0.5)
    assert runs.get(again.run_id) is not None
    assert runs.recent(1)[0]["state"] == "running"  # its runner is at work: it stays running


def test_a_run_that_cannot_start_leaves_nothing_running(served: Served) -> None:
    runs = served.app.runs
    runs.runners["steps"] = Silent(raises=True)
    with pytest.raises(server.ApiError) as raised:
        runs.start(spec(), plan(), {})
    assert raised.value.status == 500
    assert runs.current("step") is None
    shown = runs.recent(1)[0]
    assert shown["state"] == "failed"
    assert shown["error"]["message"] == "A test run could not start"


def test_a_run_ends_even_when_its_failure_cannot_be_put_in_words(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(lines: list[str], timed_out: bool) -> dict[str, Any]:
        raise ValueError("a defect")

    monkeypatch.setattr(server, "classify_failure", broken)
    runs = served.app.runs
    runs.runners["steps"] = Silent(working=True)
    run = runs.start(spec(), plan(), {})
    emit = runs._emitter("steps")
    emit(core.End("steps", plan(), False, False, ()))
    assert runs.current("step") is None
    assert run.state == "failed"
    assert run.error is not None
    assert run.error["code"] == "failed"


def test_a_runner_without_a_thread_is_not_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines: list[str] = []

    def emit(event: core.RunnerEvent) -> None:
        if isinstance(event, core.Line):
            lines.append(event.text)

    runner = core.Runner("steps", tmp_path, core.program_env(), emit)

    def no_thread(self: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", no_thread)
    assert runner.start(plan()) is False
    monkeypatch.undo()
    assert runner.busy is False
    assert any("could not start" in line for line in lines)
    world = demo.World()
    fake = demo.DemoRunner("steps", lambda event: None, world, 0.0)
    monkeypatch.setattr(threading.Thread, "start", no_thread)
    assert fake.start(plan()) is False
    monkeypatch.undo()
    assert fake.busy is False


def open_stream(served: Served) -> socket.socket:
    """An event stream on a raw socket, read up to its first event: what a window holds."""
    sock = socket.create_connection(("127.0.0.1", served.port), timeout=5)
    sock.sendall(
        (
            f"GET /api/events HTTP/1.1\r\nHost: {served.host}\r\n"
            f"X-Panel-Token: {served.token}\r\nAccept: text/event-stream\r\n\r\n"
        ).encode()
    )
    data = b""
    while b"event: hello" not in data:
        chunk = sock.recv(65536)
        assert chunk, "the stream closed before its hello"
        data += chunk
    return sock


def kept_alive(served: Served, path: str = "/api/meta") -> http.client.HTTPConnection:
    """A connection that made one request and stays open, as a browser's pool keeps it."""
    connection = http.client.HTTPConnection("127.0.0.1", served.port, timeout=5)
    connection.request("GET", path, headers={"Host": served.host, "X-Panel-Token": served.token})
    connection.getresponse().read()
    return connection


def test_threads_stay_bounded_after_many_reconnects_and_reloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server.Handler, "timeout", 0.5)
    monkeypatch.setattr(server, "PING_SECONDS", 0.2)
    with Served() as served:
        served.demo({"speed": 20})
        served.get("/api/status")
        time.sleep(0.5)
        baseline = threading.active_count()
        held: list[Any] = []
        for _ in range(40):  # a reload: the old stream drops, a new one opens, files load
            open_stream(served).close()
            held.append(open_stream(served))  # and a window that went away without a word
            held.extend(kept_alive(served, path) for path in ("/api/meta", "/api/actions"))
            assert served.app.hub.count() <= server.MAX_STREAMS
            time.sleep(0.1)
        wait_for(lambda: threading.active_count() <= baseline + server.MAX_STREAMS + 3, 10)
        assert served.app.hub.count() <= server.MAX_STREAMS
        for item in held:
            item.close()
        wait_for(lambda: threading.active_count() <= baseline + 3, 10)
        assert served.get("/api/meta").status == 200


def test_a_connection_past_the_limit_is_closed_unanswered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "MAX_CONNECTIONS", 3)
    monkeypatch.setattr(server.Handler, "timeout", 1.0)
    with Served() as served:
        held = [kept_alive(served) for _ in range(3)]
        extra = socket.create_connection(("127.0.0.1", served.port), timeout=5)
        extra.sendall(f"GET /api/meta HTTP/1.1\r\nHost: {served.host}\r\n\r\n".encode())
        with contextlib.suppress(ConnectionResetError):
            assert extra.recv(1024) == b""
        extra.close()
        for connection in held:
            connection.close()
        wait_for(lambda: served.get("/api/meta").status == 200, 10)


def test_the_server_binds_without_a_reverse_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_dns(name: str = "") -> str:
        raise AssertionError("no reverse lookup")

    monkeypatch.setattr(socket, "getfqdn", no_dns)
    made = server.make_server(demo.DemoBackend(), prefs=server.Prefs(None))
    try:
        assert made.server_name == "127.0.0.1"
        assert made.server_port == made.app.port
    finally:
        made.server_close()


def test_only_a_helper_nobody_owns_stops_after_ten_minutes() -> None:
    reason = server.exit_reason
    assert reason(owned=True, detached=False, parent_gone=False, idle=True) is None
    assert reason(owned=False, detached=False, parent_gone=False, idle=True) == (
        "ten minutes passed without a window"
    )
    assert reason(owned=False, detached=True, parent_gone=True, idle=False) is None
    assert reason(owned=True, detached=False, parent_gone=True, idle=False) == "its parent exited"
    assert reason(owned=False, detached=False, parent_gone=False, idle=False) is None


def start_script() -> tuple[subprocess.Popen[bytes], int, str]:
    proc = subprocess.Popen(
        [sys.executable, "-B", str(SCRIPT), "--demo"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdout is not None
    data = json.loads(proc.stdout.readline())
    return proc, int(data["port"]), str(data["token"])


def test_quit_stops_the_helper() -> None:
    proc, port, token = start_script()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(
        "POST",
        "/api/quit",
        body=b"",
        headers={"Host": f"127.0.0.1:{port}", "X-Panel-Token": token, "Content-Length": "0"},
    )
    reply = connection.getresponse()
    assert reply.status == 202
    assert json.loads(reply.read()) == {"ok": True, "quitting": True}
    assert proc.wait(timeout=10) == 0
    assert proc.stderr is not None
    assert proc.stderr.read().decode().strip().splitlines()[-1] == (
        "panel_server: exiting: asked to quit"
    )


def test_quit_without_an_owner_to_stop_says_so(served: Served) -> None:
    reply = served.post("/api/quit")
    assert reply.status == 202
    assert reply.json == {"ok": True, "quitting": False}
    assert served.post("/api/quit", token=None).status == 401


def test_open_connections_do_not_keep_the_helper_from_stopping() -> None:
    proc, port, token = start_script()
    headers = {"Host": f"127.0.0.1:{port}", "X-Panel-Token": token}
    stream = socket.create_connection(("127.0.0.1", port), timeout=5)
    request = f"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-Panel-Token: {token}"
    stream.sendall(f"{request}\r\n\r\n".encode())
    busy = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    stop = threading.Event()

    def beat() -> None:  # a window's heartbeat on one kept-alive connection
        while not stop.is_set():
            try:
                busy.request("POST", "/api/heartbeat", body=b"", headers=headers)
                busy.getresponse().read()
            except OSError:
                return
            time.sleep(0.3)

    threading.Thread(target=beat, daemon=True).start()
    time.sleep(1.0)
    assert proc.stdin is not None
    closed = time.monotonic()
    proc.stdin.close()
    try:
        assert proc.wait(timeout=server.SHUTDOWN_SECONDS + 3) == 0
    finally:
        stop.set()
        stream.close()
        if proc.poll() is None:
            proc.kill()
    assert time.monotonic() - closed < server.SHUTDOWN_SECONDS + 2
