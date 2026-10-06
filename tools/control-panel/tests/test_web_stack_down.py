"""make web-stack-down signals only the processes its pid files name.

The panel runs the target from Stop, Restart, Reset and Stop everything, and writes
var/web-stack/web.pid itself. A pid file can outlive its process (a reboot, a crash), and its pid
can then belong to any other program, a control panel window among them. The recipe signals a
pid only while it still runs that file's service (a uvicorn of the service, or the web app's
pnpm --filter web dev or next dev), and otherwise just removes the file.

The test runs the real recipe in a temporary directory, against processes it starts itself.
"""

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import panel_core as core
import pytest

MAKEFILE = Path(__file__).resolve().parents[3] / "Makefile"
SLEEP = "import time; time.sleep(60)"
# Starts a program and leaves it: like make web-stack's nohup'd services, it is then nobody's
# child, so it is reaped as soon as it exits
ORPHAN = (
    "import subprocess, sys; d = subprocess.DEVNULL; "
    "print(subprocess.Popen(sys.argv[1:], stdin=d, stdout=d, stderr=d).pid)"
)


@pytest.fixture
def orphans() -> Iterator[list[int]]:
    pids: list[int] = []
    yield pids
    for pid in pids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


def wait_until_gone(pid: int, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not core.pid_alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_web_stack_down_leaves_a_pid_that_runs_another_program_alone(
    tmp_path: Path, orphans: list[int]
) -> None:
    if not MAKEFILE.is_file() or shutil.which("make") is None:
        pytest.skip("needs the repo's Makefile and make")

    def start(*argv: str) -> int:
        done = subprocess.run(
            [sys.executable, "-c", ORPHAN, sys.executable, "-c", SLEEP, *argv],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        pid = int(done.stdout)
        orphans.append(pid)
        return pid

    identity = start("uvicorn", "identity.main:app", "--port", "8001")
    web = start("--filter", "web", "dev")
    recycled = start("tools/control-panel/control_panel.py")  # a panel window got the pid
    unrelated = start("http.server")
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    pids = tmp_path / "var" / "web-stack"
    pids.mkdir(parents=True)
    for name, pid in (
        ("identity", identity),
        ("web", web),
        ("rulebook", recycled),
        ("qa", unrelated),
        ("eval", gone.pid),
    ):
        (pids / f"{name}.pid").write_text(f"{pid}\n")

    done = subprocess.run(
        [
            "make",
            "-f",
            str(MAKEFILE),
            "-C",
            str(tmp_path),
            "--no-print-directory",
            "web-stack-down",
        ],
        env=core.program_env(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert done.returncode == 0, done.stderr
    assert sorted(done.stdout.splitlines()) == sorted(
        [
            "  eval was not running",
            f"  identity stopped (pid {identity})",
            f"  qa: pid {unrelated} now belongs to another program; left alone",
            f"  rulebook: pid {recycled} now belongs to another program; left alone",
            f"  web stopped (pid {web})",
        ]
    )
    assert wait_until_gone(identity)
    assert wait_until_gone(web)
    assert core.pid_alive(recycled)
    assert core.pid_alive(unrelated)
    assert list(pids.glob("*.pid")) == []
