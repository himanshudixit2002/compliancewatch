"""ComplianceWatch.app carries its own copy of the panel with a BUILD stamp, and a launcher that
runs that copy on the checkout, with the checkout's Python and CW_CONTROL_PANEL_REPO set.

The script runs into a temporary destination against a stand-in checkout; nothing touches the
Desktop.
"""

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import panel_core as core
import pytest

HERE = Path(__file__).resolve().parents[1]
SCRIPT = HERE / "install-app.sh"


def checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "my checkout"
    (repo / ".git").mkdir(parents=True)
    (repo / "Makefile").write_text("control-panel-app:\n")
    return repo


def install(dest: Path, repo: Path) -> subprocess.CompletedProcess[str]:
    if shutil.which("bash") is None:
        pytest.skip("needs bash")
    env = {**core.program_env(), "CW_CONTROL_PANEL_REPO": str(repo)}
    return subprocess.run(
        ["bash", str(SCRIPT), str(dest)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_the_app_carries_its_own_panel_and_runs_it_on_the_checkout(tmp_path: Path) -> None:
    repo = checkout(tmp_path)
    done = install(tmp_path, repo)
    assert done.returncode == 0, done.stderr
    app = tmp_path / "ComplianceWatch.app"
    panel = app / "Contents" / "Resources" / "control-panel"
    assert sorted(path.name for path in panel.iterdir()) == [
        "BUILD",
        "control_panel.py",
        "panel_core.py",
    ]
    for name in ("control_panel.py", "panel_core.py"):
        assert (panel / name).read_bytes() == (HERE / name).read_bytes()
    build = core.read_build(panel)
    assert set(build) == {"built", "commit", "files", "source"}
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", build["built"])
    assert re.fullmatch(r"none|[0-9a-f]{7,}(\+changes)?", build["commit"])
    assert re.fullmatch(r"[0-9a-f]{12}", build["files"])
    assert build["source"] == str(HERE)
    assert core.describe_build(build).startswith(f"Panel build {build['built']} · ")
    assert (
        "CFBundleExecutable</key><string>ComplianceWatch<"
        in (app / "Contents" / "Info.plist").read_text()
    )

    launcher = app / "Contents" / "MacOS" / "ComplianceWatch"
    assert os.access(launcher, os.X_OK)
    lines = launcher.read_text().splitlines()
    export = next(line for line in lines if line.startswith("export CW_CONTROL_PANEL_REPO="))
    assert shlex.split(export) == ["export", f"CW_CONTROL_PANEL_REPO={repo}"]
    assert [line for line in lines if line != export] == [
        "#!/bin/bash",
        "# Opens the control panel this bundle carries, on the checkout it was built for.",
        'panel="$(cd "$(dirname "$0")/../Resources/control-panel" && pwd)" || exit 1',
        'export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"',
        'cd "$CW_CONTROL_PANEL_REPO" || exit 1',
        "[ -x .venv/bin/python ] || uv sync --all-packages >/dev/null 2>&1",
        'exec .venv/bin/python "$panel/control_panel.py"',
    ]


def test_running_it_again_replaces_the_app(tmp_path: Path) -> None:
    repo = checkout(tmp_path)
    assert install(tmp_path, repo).returncode == 0
    stale = tmp_path / "ComplianceWatch.app" / "Contents" / "Resources" / "control-panel" / "old.py"
    stale.write_text("an earlier panel's file")
    assert install(tmp_path, repo).returncode == 0
    assert not stale.exists()


def test_it_refuses_a_directory_that_is_not_a_checkout(tmp_path: Path) -> None:
    elsewhere = tmp_path / "not a checkout"
    elsewhere.mkdir()
    done = install(tmp_path, elsewhere)
    assert done.returncode == 1
    assert "is not a ComplianceWatch checkout; set CW_CONTROL_PANEL_REPO=<checkout>" in done.stdout
    assert not (tmp_path / "ComplianceWatch.app").exists()
