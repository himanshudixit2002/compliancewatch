"""make web-stack points every service at the stack's own ports, and make web-stack-down signals
only the processes its pid files name.

A stack on another SERVICE_PORT_BASE (a second clone, the control app's web check on 9400) must
never call a service of the stack on 8001-8010: make web-stack gives every service every address
it has of another on its own base, whatever .env says.

The panel runs make web-stack-down from Stop, Restart, Reset and Stop everything, and writes
var/web-stack/web.pid itself. A pid file can outlive its process (a reboot, a crash), and its pid
can then belong to any other program, a control panel window among them. The recipe signals a
pid only while it still runs that file's service (a uvicorn of the service, or the web app's
pnpm --filter web dev or next dev), and otherwise just removes the file.

The tests run the real recipes in a temporary directory: make web-stack with a uv that only
prints the environment it was given, and make web-stack-down against processes the test starts.
"""

import contextlib
import os
import re
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
ROOT = Path(os.environ.get(core.REPO_ENV) or Path(__file__).resolve().parents[3])
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


ON_9400 = {
    "CW_IDENTITY_URL": "http://localhost:9401",
    "CW_AUTH_JWKS_URL": "http://localhost:9401/v1/identity/.well-known/jwks.json",
    "CW_PROFILE_URL": "http://localhost:9402",
    "CW_RULEBOOK_URL": "http://localhost:9403",
    "CW_OBLIGATION_URL": "http://localhost:9405",
    "CW_LLM_GATEWAY_URL": "http://localhost:9408",
    "CW_EVAL_GATEWAY_URL": "http://localhost:9408",
}
_LOCALHOST_URL = re.compile(
    r'^\s+([a-z_]+_url):\s*str\s*=\s*"http://(?:localhost|127\.0\.0\.1):\d+', re.M
)
"""A setting whose default is a URL on this machine: one service's address of another."""


def web_stack(tmp_path: Path, *variables: str) -> dict[str, dict[str, str]]:
    """make web-stack in tmp_path with a uv that prints the environment each service would get;
    that environment by service."""
    env = {
        key: value
        for key, value in core.program_env().items()
        if not key.startswith("CW_") or key == "CW_PIPELINE_CRAWL_ENABLED"
    }
    for key in ("SERVICE_PORT_BASE", "WEB_PORT"):
        env.pop(key, None)
    if not MAKEFILE.is_file() or shutil.which("make") is None:
        pytest.skip("needs the repo's Makefile and make")
    if shutil.which("uv", path=env["PATH"]) is None:
        pytest.skip("make web-stack checks that uv is installed")
    fake = tmp_path / "fake-uv"
    fake.write_text("#!/bin/sh\nenv\n")
    fake.chmod(0o755)
    done = subprocess.run(
        [
            "make",
            "-f",
            str(MAKEFILE),
            "-C",
            str(tmp_path),
            "--no-print-directory",
            "web-stack",
            f"UV={fake}",
            *variables,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    logs = tmp_path / "var" / "web-stack"
    printed: dict[str, dict[str, str]] = {}
    deadline = time.monotonic() + 10
    for service in core.SERVICES:
        log = logs / f"{service}.log"
        while "CW_RULEBOOK_URL=" not in (log.read_text() if log.is_file() else ""):
            assert time.monotonic() < deadline, f"{service} printed nothing"
            time.sleep(0.05)
        printed[service] = dict(
            line.split("=", 1) for line in log.read_text().splitlines() if "=" in line
        )
    return printed


def test_web_stack_points_every_service_at_the_stack_s_own_ports(tmp_path: Path) -> None:
    # .env names the services on 8001-8010, as a developer's does: the stack's own base wins
    (tmp_path / ".env").write_text(
        "CW_IDENTITY_URL=http://localhost:8001\nCW_EVAL_GATEWAY_URL=http://localhost:8008\n"
    )
    printed = web_stack(tmp_path, "SERVICE_PORT_BASE=9400", "WEB_PORT=3410")
    for service, env in printed.items():
        assert {key: env.get(key) for key in ON_9400} == ON_9400, service
        assert env["CW_WEB_BASE_URL"] == "http://localhost:3410", service
    assert (tmp_path / "var" / "web-stack" / "store").read_text() == "store=memory\nbase=9400\n"


def test_web_stack_keeps_a_web_address_that_is_set(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("CW_WEB_BASE_URL=https://cw.example.test\n")
    printed = web_stack(tmp_path)
    assert {env["CW_WEB_BASE_URL"] for env in printed.values()} == {"https://cw.example.test"}
    assert {env["CW_IDENTITY_URL"] for env in printed.values()} == {"http://localhost:8001"}


def test_every_localhost_url_the_services_default_to_is_on_the_stack_s_base() -> None:
    settings = [
        *ROOT.glob("services/*/src/*/settings.py"),
        ROOT / "packages" / "py-common" / "src" / "py_common" / "settings.py",
    ]
    found = {
        f"CW_{match.group(1).upper()}"
        for path in settings
        if path.is_file()
        for match in _LOCALHOST_URL.finditer(path.read_text(encoding="utf-8"))
    }
    if not found:
        pytest.skip(f"no service settings under {ROOT}")
    # the web app's address for links is the web app's, on WEB_PORT, not on the services' base
    assert found <= {*ON_9400, "CW_WEB_BASE_URL"}, found - set(ON_9400)
    makefile = MAKEFILE.read_text(encoding="utf-8")
    for name in found:
        assert f'{name}="' in makefile, name
