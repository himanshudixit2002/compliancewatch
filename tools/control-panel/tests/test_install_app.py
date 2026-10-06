"""ComplianceWatch.app carries its own copy of the control app (the helper and the UI) with a BUILD
stamp, its window (the compiled Swift shell, or a browser launcher without swiftc), the icon and
the checkout it was built for.

The script runs into a temporary destination against a stand-in checkout; nothing touches the
Desktop, and a stand-in lsregister answers for LaunchServices, so no test registers an app with
macOS.
"""

import os
import plistlib
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import panel_core as core
import pytest

HERE = Path(__file__).resolve().parents[1]
SCRIPT = HERE / "install-app.sh"
FILES = ["BUILD", "panel_catalog.py", "panel_core.py", "panel_demo.py", "panel_server.py", "ui"]


def checkout(tmp_path: Path, name: str = "my checkout") -> Path:
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True)
    (repo / "Makefile").write_text("control-panel-app:\n")
    return repo


FAKE_LSREGISTER = """#!/bin/bash
echo "$*" >> "$FAKE_LS_LOG"
if [ "$1" = -dump ] && [ -f "$FAKE_LS_DUMP" ]; then cat "$FAKE_LS_DUMP"; fi
"""

# fails the moves numbered in FAKE_MV_FAIL ("2 3"), and every move from FAKE_MV_FAIL_FROM on
FAKE_MV = """#!/bin/bash
n=$(( $(cat "$FAKE_MV_COUNT" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$FAKE_MV_COUNT"
case " ${FAKE_MV_FAIL:-} " in *" $n "*) echo "mv: simulated failure" >&2; exit 1 ;; esac
if [ -n "${FAKE_MV_FAIL_FROM:-}" ] && [ "$n" -ge "$FAKE_MV_FAIL_FROM" ]; then
  echo "mv: simulated failure" >&2
  exit 1
fi
exec /bin/mv "$@"
"""


def stand_in(folder: Path, name: str, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text)
    path.chmod(0o755)
    return path


def install(
    dest: Path,
    repo: Path,
    shell: str = "browser",
    *,
    fail_moves: str = "",
    fail_moves_from: int = 0,
    extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if shutil.which("bash") is None:
        pytest.skip("needs bash")
    fakes = repo.parent / "fakes"
    env = {
        **core.program_env(),
        "CW_CONTROL_PANEL_REPO": str(repo),
        "CW_CONTROL_APP_SHELL": shell,
        "CW_CONTROL_APP_LSREGISTER": str(stand_in(fakes, "lsregister", FAKE_LSREGISTER)),
        "FAKE_LS_LOG": str(fakes / "lsregister.log"),
        "FAKE_LS_DUMP": str(fakes / "lsregister.dump"),
        **(extra or {}),
    }
    if fail_moves or fail_moves_from:
        bin_dir = fakes / "bin"
        stand_in(bin_dir, "mv", FAKE_MV)
        (fakes / "mv.count").unlink(missing_ok=True)
        env |= {
            "PATH": f"{bin_dir}:{env.get('PATH', '/usr/bin:/bin')}",
            "FAKE_MV_COUNT": str(fakes / "mv.count"),
            "FAKE_MV_FAIL": fail_moves,
            "FAKE_MV_FAIL_FROM": str(fail_moves_from or ""),
        }
    return subprocess.run(
        ["bash", str(SCRIPT), str(dest)],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def files_under(folder: Path) -> list[str]:
    return sorted(str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file())


def test_the_app_carries_the_helper_the_ui_and_the_checkout(tmp_path: Path) -> None:
    repo = checkout(tmp_path)
    done = install(tmp_path, repo)
    assert done.returncode == 0, done.stdout + done.stderr
    app = tmp_path / "ComplianceWatch.app"
    panel = app / "Contents" / "Resources" / "control-panel"
    assert sorted(path.name for path in panel.iterdir()) == FILES
    for name in FILES[1:-1]:
        assert (panel / name).read_bytes() == (HERE / name).read_bytes()
    shipped = [name for name in files_under(HERE / "ui") if not name.split("/")[-1].startswith(".")]
    assert files_under(panel / "ui") == shipped
    assert not (panel / "ui-tests").exists()
    assert not (panel / "control_panel.py").exists()

    build = core.read_build(panel)
    assert set(build) == {"built", "commit", "files", "source"}
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", build["built"])
    assert re.fullmatch(r"none|[0-9a-f]{7,}(\+changes)?", build["commit"])
    assert re.fullmatch(r"[0-9a-f]{12}", build["files"])
    assert build["source"] == str(HERE)

    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == "ComplianceWatch"
    assert info["CFBundleIdentifier"] == "local.compliancewatch.control-panel"
    assert info["CFBundleDisplayName"] == "ComplianceWatch Control"
    assert info["CWCheckout"] == str(repo)
    assert info["CWShell"] == "browser"
    assert info["NSAppTransportSecurity"] == {"NSAllowsLocalNetworking": True}
    if shutil.which("iconutil"):
        assert info["CFBundleIconFile"] == "AppIcon"
        assert (app / "Contents" / "Resources" / "AppIcon.icns").read_bytes()[:4] == b"icns"
    else:
        assert "CFBundleIconFile" not in info
    assert not list(tmp_path.glob(".ComplianceWatch-build.*"))


def test_without_swift_the_app_opens_the_ui_in_a_browser(tmp_path: Path) -> None:
    repo = checkout(tmp_path, "it's a checkout & more")
    done = install(tmp_path, repo)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "window: a browser" in done.stdout
    app = tmp_path / "ComplianceWatch.app"
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CWCheckout"] == str(repo)
    launcher = app / "Contents" / "MacOS" / "ComplianceWatch"
    assert os.access(launcher, os.X_OK)
    lines = launcher.read_text().splitlines()
    assert lines[0] == "#!/bin/bash"
    export = next(line for line in lines if line.startswith("export CW_CONTROL_PANEL_REPO="))
    assert shlex.split(export) == ["export", f"CW_CONTROL_PANEL_REPO={repo}"]
    start = next(line for line in lines if "panel_server.py" in line)
    assert start.startswith(
        'nohup .venv/bin/python -B "$panel/panel_server.py" --open app --detach'
    )
    assert start.endswith("&")
    assert "make" not in start
    assert "token" not in launcher.read_text()


def has_swiftc() -> bool:
    if shutil.which("xcrun") is None:
        return False
    found = subprocess.run(["xcrun", "--find", "swiftc"], capture_output=True, check=False)
    return found.returncode == 0


@pytest.mark.skipif(not has_swiftc(), reason="needs swiftc (Xcode or its command line tools)")
def test_with_swift_the_app_is_its_own_window(tmp_path: Path) -> None:
    repo = checkout(tmp_path)
    done = install(tmp_path, repo, shell="swift")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "window: the Swift shell" in done.stdout
    app = tmp_path / "ComplianceWatch.app"
    binary = (app / "Contents" / "MacOS" / "ComplianceWatch").read_bytes()
    assert binary[:4] in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")  # Mach-O, thin or fat
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CWShell"] == "swift"


def test_running_it_again_replaces_the_app(tmp_path: Path) -> None:
    repo = checkout(tmp_path)
    assert install(tmp_path, repo).returncode == 0
    stale = tmp_path / "ComplianceWatch.app" / "Contents" / "Resources" / "control-panel" / "old.py"
    stale.write_text("an earlier panel's file")
    assert install(tmp_path, repo).returncode == 0
    assert not stale.exists()
    assert not list(tmp_path.glob(".ComplianceWatch-build.*"))


def installed_with_a_mark(tmp_path: Path) -> tuple[Path, Path]:
    """An installed app with a file only the old app has, and the checkout it was built for."""
    repo = checkout(tmp_path)
    done = install(tmp_path, repo)
    assert done.returncode == 0, done.stdout + done.stderr
    mark = tmp_path / "ComplianceWatch.app" / "Contents" / "Resources" / "old-mark"
    mark.write_text("the app installed before")
    return repo, mark


def leftovers(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.glob(".ComplianceWatch-*"))


def test_a_failed_move_in_puts_the_old_app_back(tmp_path: Path) -> None:
    repo, mark = installed_with_a_mark(tmp_path)
    # move 1 takes the old app aside; move 2, the new app in, fails
    done = install(tmp_path, repo, fail_moves="2")
    assert done.returncode != 0
    assert "the install failed, so the old app is back at" in done.stdout
    assert mark.read_text() == "the app installed before"
    assert leftovers(tmp_path) == []


def test_a_failed_move_aside_leaves_the_old_app_where_it_is(tmp_path: Path) -> None:
    repo, mark = installed_with_a_mark(tmp_path)
    done = install(tmp_path, repo, fail_moves="1")
    assert done.returncode != 0
    assert mark.read_text() == "the app installed before"
    assert leftovers(tmp_path) == []


def test_when_the_old_app_cannot_move_back_it_is_kept_and_named(tmp_path: Path) -> None:
    repo, mark = installed_with_a_mark(tmp_path)
    # every move after the first fails: the new app cannot go in, the old one cannot come back
    done = install(tmp_path, repo, fail_moves_from=2)
    assert done.returncode != 0
    kept = list(tmp_path.glob(".ComplianceWatch-old.*/ComplianceWatch.app"))
    assert len(kept) == 1
    assert (kept[0] / "Contents" / "Resources" / "old-mark").read_text() == (
        "the app installed before"
    )
    assert f"the old app is kept at {kept[0]}; move it back to" in done.stdout
    assert not (tmp_path / "ComplianceWatch.app").exists()
    assert not list(tmp_path.glob(".ComplianceWatch-build.*"))
    assert not mark.exists()


def test_launchservices_forgets_the_paths_an_install_leaves(tmp_path: Path) -> None:
    repo, _ = installed_with_a_mark(tmp_path)
    app = tmp_path / "ComplianceWatch.app"
    elsewhere = tmp_path / "Applications" / "ComplianceWatch.app"
    (elsewhere / "Contents").mkdir(parents=True)
    gone = tmp_path / "gone" / "ComplianceWatch.app"
    other = tmp_path / "Applications" / "Other.app"

    def record(path: Path, ident: str) -> str:
        pad = " " * 23
        return f"{'-' * 80}\npath:{pad}{path} (0x1a2b)\nidentifier:{pad[:-6]}{ident}\n"

    fakes = tmp_path / "fakes"
    (fakes / "lsregister.dump").write_text(
        record(app, "local.compliancewatch.control-panel")
        + record(elsewhere, "local.compliancewatch.control-panel")
        + record(gone, "local.compliancewatch.control-panel")
        + record(other, "local.example.other")
    )
    (fakes / "lsregister.log").unlink(missing_ok=True)
    done = install(tmp_path, repo)
    assert done.returncode == 0, done.stdout + done.stderr
    calls = (fakes / "lsregister.log").read_text().splitlines()
    assert calls[0] == "-dump"
    assert calls[-1] == f"-f {app}"  # registered again: Finder and the Dock read the new icon
    forgotten = [call.removeprefix("-u ") for call in calls[1:-1]]
    assert str(elsewhere) in forgotten
    assert str(gone) in forgotten
    assert any(
        re.fullmatch(
            rf"{re.escape(str(tmp_path))}/\.ComplianceWatch-old\.\w+/ComplianceWatch\.app", p
        )
        for p in forgotten
    )
    assert any(
        re.fullmatch(
            rf"{re.escape(str(tmp_path))}/\.ComplianceWatch-build\.\w+/ComplianceWatch\.app", p
        )
        for p in forgotten
    )
    assert str(app) not in forgotten
    assert str(other) not in forgotten
    assert f"another copy of this app is at {elsewhere}" in done.stdout
    assert f"another copy of this app is at {gone}" not in done.stdout
    assert leftovers(tmp_path) == []


def test_a_test_build_has_its_own_name_and_bundle_id(tmp_path: Path) -> None:
    repo = checkout(tmp_path)
    extra = {
        "CW_CONTROL_APP_NAME": "ComplianceWatch Smoke",
        "CW_CONTROL_APP_ID": "local.compliancewatch.control-panel.smoke",
    }
    done = install(tmp_path, repo, extra=extra)
    assert done.returncode == 0, done.stdout + done.stderr
    assert not (tmp_path / "ComplianceWatch.app").exists()
    info = plistlib.loads(
        (tmp_path / "ComplianceWatch Smoke.app" / "Contents" / "Info.plist").read_bytes()
    )
    assert info["CFBundleName"] == "ComplianceWatch Smoke"
    assert info["CFBundleDisplayName"] == "ComplianceWatch Smoke"
    assert info["CFBundleIdentifier"] == "local.compliancewatch.control-panel.smoke"
    for bad in ({"CW_CONTROL_APP_NAME": "../elsewhere"}, {"CW_CONTROL_APP_ID": "no dots"}):
        refused = install(tmp_path, repo, extra=bad)
        assert refused.returncode == 1
        assert refused.stdout.startswith("error: CW_CONTROL_APP_")


def test_it_refuses_a_directory_that_is_not_a_checkout(tmp_path: Path) -> None:
    elsewhere = tmp_path / "not a checkout"
    elsewhere.mkdir()
    done = install(tmp_path, elsewhere)
    assert done.returncode == 1
    assert "is not a ComplianceWatch checkout; set CW_CONTROL_PANEL_REPO=<checkout>" in done.stdout
    assert not (tmp_path / "ComplianceWatch.app").exists()
