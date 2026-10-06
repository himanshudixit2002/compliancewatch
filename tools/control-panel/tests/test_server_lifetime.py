"""How long the helper lives: one hand-off line with the port and the token and nothing else on
stdout; it exits when its input pipe closes, when its parent exits (unless detached), on SIGTERM,
and after ten minutes without an authenticated request. These start the real script with
``--demo``: no program of the checkout runs."""

import http.client
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import panel_server as server
import pytest
from serverkit import Served

SCRIPT = Path(server.__file__).resolve()


def start(*args: str, stdin: int = subprocess.PIPE) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-B", str(SCRIPT), "--demo", *args],
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def hand_off(proc: subprocess.Popen[bytes]) -> dict[str, object]:
    assert proc.stdout is not None
    line = proc.stdout.readline()
    data = json.loads(line)
    assert isinstance(data, dict)
    return data


def meta(port: object, token: object) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", int(str(port)), timeout=10)
    connection.request(
        "GET", "/api/meta", headers={"Host": f"127.0.0.1:{port}", "X-Panel-Token": str(token)}
    )
    status = connection.getresponse().status
    connection.close()
    return status


def finish(proc: subprocess.Popen[bytes], seconds: float = 15) -> tuple[int, str]:
    code = proc.wait(timeout=seconds)
    assert proc.stderr is not None
    return code, proc.stderr.read().decode()


def gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_it_hands_off_once_and_stops_when_its_input_closes() -> None:
    proc = start()
    data = hand_off(proc)
    assert set(data) == {"port", "token"}
    assert isinstance(data["token"], str)
    assert len(data["token"]) >= 40
    assert meta(data["port"], data["token"]) == 200
    assert proc.stdin is not None
    proc.stdin.close()
    code, err = finish(proc)
    assert code == 0
    assert err.strip().splitlines()[-1] == "panel_server: exiting: stdin closed"
    assert str(data["token"]) not in err


def test_sigterm_stops_it() -> None:
    proc = start()
    hand_off(proc)
    proc.send_signal(signal.SIGTERM)
    code, err = finish(proc)
    assert code == 0
    assert err.strip().splitlines()[-1] == "panel_server: exiting: SIGTERM"


def run_through_a_parent(*args: str) -> tuple[dict[str, object], int, subprocess.Popen[bytes]]:
    """Starts the helper from a short-lived parent, which prints the hand-off and the helper's
    pid, then exits: the helper's input is not a pipe."""
    code = (
        "import subprocess, sys\n"
        f"p = subprocess.Popen([sys.executable, '-B', {str(SCRIPT)!r}, '--demo', *{list(args)!r}],"
        " stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)\n"
        "print(p.stdout.readline().decode().strip())\n"
        "print(p.pid)\n"
    )
    parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE)
    assert parent.stdout is not None
    data = json.loads(parent.stdout.readline())
    pid = int(parent.stdout.readline())
    parent.wait(timeout=10)
    return data, pid, parent


def test_it_stops_when_its_parent_exits() -> None:
    _, pid, _ = run_through_a_parent()
    deadline = time.monotonic() + 10
    while not gone(pid):
        assert time.monotonic() < deadline, "the helper outlived its parent"
        time.sleep(0.1)


def test_detached_it_outlives_its_parent_until_told_to_stop() -> None:
    data, pid, _ = run_through_a_parent("--detach")
    try:
        time.sleep(2.5)
        assert not gone(pid)
        assert meta(data["port"], data["token"]) == 200
    finally:
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while not gone(pid):
        assert time.monotonic() < deadline
        time.sleep(0.1)


def test_it_expires_without_an_authenticated_request() -> None:
    now = [0.0]
    lifetime = server.Lifetime(lambda: now[0], 600)
    now[0] = 599
    assert not lifetime.expired()
    lifetime.touch()
    now[0] = 1199
    assert not lifetime.expired()
    now[0] = 1200.5
    assert lifetime.expired()


def test_only_an_authenticated_request_counts_as_a_sign_of_life() -> None:
    with Served() as served:
        before = served.app.lifetime.last
        time.sleep(0.05)
        served.get("/api/status", token=None)
        served.get("/", token=None)
        assert served.app.lifetime.last == before
        served.post("/api/heartbeat")
        assert served.app.lifetime.last > before


def test_end_of_input_on_a_pipe_is_noticed() -> None:
    read, write = os.pipe()
    seen = threading.Event()
    watcher = threading.Thread(target=server.watch_stdin, args=(seen.set, read), daemon=True)
    watcher.start()
    os.write(write, b"anything\n")
    time.sleep(0.1)
    assert not seen.is_set()
    os.close(write)
    assert seen.wait(5)
    os.close(read)


def test_a_person_s_terminal_never_shows_the_token() -> None:
    token = "k" * 43
    assert json.loads(server.hand_off_line(5000, token, opened=False, tty=False)) == {
        "port": 5000,
        "token": token,
    }
    assert json.loads(server.hand_off_line(5000, token, opened=True, tty=False))["token"] == token
    words = server.hand_off_line(5000, token, opened=True, tty=True)
    assert token not in words
    assert "http://127.0.0.1:5000" in words


def test_the_window_opens_in_chrome_s_app_mode_or_the_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[tuple[str, ...]] = []
    opened: list[str] = []
    monkeypatch.setattr(server.subprocess, "Popen", lambda argv, **_: started.append(argv))
    monkeypatch.setattr(server.webbrowser, "open", opened.append)
    url = "http://127.0.0.1:5000/#launch=l-abc"
    monkeypatch.setattr(server, "CHROME_APPS", (tmp_path / "missing.app",))
    server.open_window(url, app=True)
    assert opened == [url]
    assert started == []
    chrome = tmp_path / "Google Chrome.app"
    chrome.mkdir()
    monkeypatch.setattr(server, "CHROME_APPS", (chrome,))
    server.open_window(url, app=True)
    assert started == [("/usr/bin/open", "-na", str(chrome), "--args", f"--app={url}")]
    server.open_window(url, app=False)
    assert opened == [url, url]


def test_open_hands_the_window_a_launch_code_never_the_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}

    def opened(url: str, *, app: bool) -> None:
        seen["url"], seen["app"] = url, app
        port = int(url.split(":")[2].split("/")[0])
        code = url.split("#launch=", 1)[1].split("&", 1)[0]
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request(
            "POST",
            "/api/launch",
            body=json.dumps({"code": code}),
            headers={"Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"},
        )
        seen["answer"] = json.loads(connection.getresponse().read())
        connection.close()
        os.kill(os.getpid(), signal.SIGTERM)  # main's own handler stops it

    monkeypatch.setattr(server, "open_window", opened)
    kept = {number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGINT)}
    kept[signal.SIGHUP] = signal.getsignal(signal.SIGHUP)
    try:
        assert server.main(["--demo", "--open", "app"]) == 0
    finally:
        for number, handler in kept.items():
            signal.signal(number, handler)
    token = json.loads(capsys.readouterr().out.splitlines()[0])["token"]
    assert seen["app"] is True
    assert token not in str(seen["url"])
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+/#launch=l-[\w-]+", str(seen["url"]))
    assert seen["answer"] == {"token": token}
