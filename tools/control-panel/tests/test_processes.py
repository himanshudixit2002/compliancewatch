"""Which processes are the checkout's, who started them, and what a stop may signal.

The ps and lsof output below was recorded on a developer's Mac while another session ran
make product-check, an older control panel window ran the UI-only stack, and Claude Code,
desktop-commander and Colima ran from the same directory; paths and ids are anonymised.
"""

from pathlib import Path

import panel_core as core
import pytest

REPO = Path("/Users/dev/cw")
SELF = 90000

PS = """\
    1     0     1 18-02:00:00 /sbin/launchd
 6841  1174  6841 18:10:57 /Applications/Claude.app/Contents/Helpers/disclaimer --pgroup -- claude
 6842  6841  6841 18:10:57 /Users/dev/Library/Application Support/claude --add-dir /Users/dev/cw
 6850  1572  6850 18:10:57 /bin/zsh -l
 6913  6842  6841 18:10:57 npm exec @wonderwhy-er/desktop-commander@latest
 7034  6913  6841 18:10:56 node /Users/dev/.npm/_npx/4b4c857f/node_modules/.bin/desktop-commander
 7936     1  7936 18:06:52 ssh: /Users/dev/.colima/_lima/colima/ssh.sock [mux]
 8555  6842  8555    01:10 /bin/zsh -c make product-check
 8662     1  8555    00:38 uv run --package compliancewatch-mvp cw-mvp serve
 8675  8662  8555    00:38 /Users/dev/cw/.venv/bin/python /Users/dev/cw/.venv/bin/cw-mvp serve
 8750  8555  8555    00:28 /Applications/Xcode.app/Contents/Developer/usr/bin/make product-check
 8752  8750  8555    00:28 /bin/bash -c env0=$(export -p); uv run --package compliancewatch-demo cw
 8755  8752  8555    00:28 uv run --package compliancewatch-demo cw-product check
 8756  8755  8555    00:28 /Users/dev/cw/.venv/bin/python /Users/dev/cw/.venv/bin/cw-product check
40958     1 40951 07:20:11 tail -n +1 -f /private/tmp/claude-501/-Users-dev-cw/scratchpad/e2e.log
75978     1 75978 02:28:08 .venv/bin/python tools/control-panel/control_panel.py
76074     1 75978 02:27:57 uv run --package compliancewatch-identity uvicorn identity.main:app
76107 76074 75978 02:27:57 /Users/dev/cw/.venv/bin/python -m uvicorn identity.main:app
76165 75978 76165 02:27:54 node /opt/homebrew/bin/pnpm --filter web dev
76174 76165 76165 02:27:54 node /Users/dev/cw/apps/web/node_modules/.bin/../next/dist/bin/next dev
76180 76174 76165 02:27:53 next-server (v16.3.8)
90000     1 90000    00:05 /Users/dev/cw/.venv/bin/python tools/control-panel/control_panel.py
90001 90000 90000    00:04 /Users/dev/cw/.venv/bin/python /Users/dev/cw/.venv/bin/uvicorn probe
90100     1 90100    00:03 /usr/bin/make worker SERVICE=qa
90101 90100 90100    00:03 /bin/bash -c env0=$(export -p); uv run --package compliancewatch-qa py
90102 90101 90100    00:03 uv run --package compliancewatch-qa python -m qa.worker
90103 90102 90100    00:03 /Users/dev/cw/.venv/bin/python -m qa.worker
91000     1 91000    00:10 /Users/dev/cw-old/.venv/bin/python -m http.server
"""

NAMES = {
    6841: "disclaimer",
    6842: "claude",
    6850: "zsh",
    6913: "node",
    7034: "node",
    7936: "ssh",
    8555: "zsh",
    8662: "uv",
    8675: "python3.12",
    8750: "gnumake",
    8752: "bash",
    8755: "uv",
    8756: "python3.12",
    40958: "tail",
    75978: "python3.12",
    76074: "uv",
    76107: "python3.12",
    76165: "node",
    76174: "node",
    76180: "node",
    90000: "python3.12",
    90001: "python3.12",
    90100: "gnumake",
    90101: "bash",
    90102: "uv",
    90103: "python3.12",
}
CWD = (
    "".join(
        f"p{pid}\nc{name}\nfcwd\nn{'/Users/dev/cw/apps/web' if pid in (76174, 76180) else REPO}\n"
        for pid, name in NAMES.items()
    )
    + "p1\nclaunchd\nfcwd\nn/\np91000\ncpython3.12\nfcwd\nn/Users/dev/cw-old\n"
)

PROJECT = {
    8662, 8675, 8750, 8752, 8755, 8756,
    75978, 76074, 76107, 76165, 76174, 76180,
    90000, 90001, 90100, 90101, 90102, 90103,
}  # fmt: skip
PID_FILES = {76074: "make web-stack", 76165: "panel web app", 8662: "make product"}


def snapshot() -> core.ProcessSnapshot:
    procs = core.parse_ps(PS)
    names = core.parse_lsof_cwd(CWD)
    project = core.project_pids(procs, names, REPO)
    origins = core.process_origins(procs, project, {90100}, PID_FILES, SELF)
    return core.ProcessSnapshot(procs, names, frozenset(project), origins, (), SELF, 0.0)


def test_ps_and_lsof_parse_every_process() -> None:
    procs = core.parse_ps(PS)
    assert len(procs) == 28
    make = "/Applications/Xcode.app/Contents/Developer/usr/bin/make product-check"
    assert procs[8750] == core.Proc(8750, 8555, 8555, 28, make)
    assert procs[1].elapsed == 18 * 86400 + 2 * 3600
    assert procs[6842].command.endswith("--add-dir /Users/dev/cw")
    names = core.parse_lsof_cwd(CWD)
    assert names[76180] == ("node", "/Users/dev/cw/apps/web")
    assert names[1] == ("launchd", "/")


def test_the_checkout_s_processes_leave_out_shells_agents_and_colima() -> None:
    procs = core.parse_ps(PS)
    names = core.parse_lsof_cwd(CWD)
    assert core.project_pids(procs, names, REPO) == PROJECT
    # Claude Code names the checkout on its command line and runs in it: still not the project's
    assert core.is_project_root("claude", procs[6842].command, str(REPO), str(REPO)) is False
    # A sibling directory that starts with the checkout's path is another checkout
    sibling = procs[91000].command
    assert core.is_project_root("python3.12", sibling, "/Users/dev/cw-old", str(REPO)) is False


def test_a_child_lsof_saw_no_directory_for_is_left_out() -> None:
    procs = core.parse_ps(PS + "90002 90000 90000    00:00 /bin/ps -axww -o pid=\n")
    names = core.parse_lsof_cwd(CWD)
    assert 90002 not in core.project_pids(procs, names, REPO)


def test_origins_name_this_panel_the_pid_files_and_other_sessions() -> None:
    origins = snapshot().origins
    assert origins[SELF] == "this panel (the window)"
    assert origins[90001] == "this panel"
    assert {origins[pid] for pid in (90100, 90101, 90102, 90103)} == {"this panel"}
    assert origins[76074] == origins[76107] == "make web-stack"
    assert origins[76165] == origins[76180] == "panel web app"
    assert origins[8662] == origins[8675] == "make product"
    assert origins[75978] == "control panel 75978"
    assert {origins[pid] for pid in (8750, 8752, 8755, 8756)} == {"other"}


def test_the_overview_names_what_other_sessions_run() -> None:
    state = snapshot()
    assert state.foreign() == [8750, 8752, 8755, 8756, 75978]
    assert state.foreign_summary(REPO) == [
        "make product-check (pid 8750, 28 s) with 3 more",
        "another control panel window (pid 75978, 2h 28m)",
    ]


def test_a_stop_never_reaches_the_panel_or_a_process_outside_the_checkout() -> None:
    state = snapshot()
    assert core.stop_target(SELF, state).refused == "that is this control panel or what started it"
    assert "not one of this checkout's processes" in core.stop_target(7034, state).refused
    assert "not one of this checkout's processes" in core.stop_target(8555, state).refused
    assert core.stop_target(424242, state).refused == "pid 424242 is not running"


def test_a_stop_never_reaches_another_control_panel_window() -> None:
    state = snapshot()
    # The older window itself: refused, where the tree would have taken its web app too
    assert core.stop_options(75978, state) == [
        core.StopTarget(
            "none", 75978, (), "that is a control panel window; close it from the window itself"
        )
    ]
    # make control-panel in a terminal: the window runs under it
    lines = (
        "95000  6850 95000    00:40 /usr/bin/make control-panel\n"
        "95001 95000 95000    00:40 .venv/bin/python tools/control-panel/control_panel.py\n"
        "95002 95001 95000    00:39 /Users/dev/cw/.venv/bin/python -m uvicorn probe:app\n"
    )
    procs = core.parse_ps(PS + lines)
    names = core.parse_lsof_cwd(
        CWD + "".join(f"p{pid}\ncpython3.12\nfcwd\nn{REPO}\n" for pid in (95000, 95001, 95002))
    )
    project = core.project_pids(procs, names, REPO)
    assert {95000, 95001, 95002} <= project
    origins = core.process_origins(procs, project, set(), PID_FILES, SELF)
    other = core.ProcessSnapshot(procs, names, frozenset(project), origins, (), SELF, 0.0)
    assert core.stop_target(95000, other).refused == "a control panel window runs under it"
    # A child of the window may stop alone: its tree holds no window, its group does
    assert core.stop_options(95002, other) == [core.StopTarget("tree", 95000, (95002,))]
    # A window run from ComplianceWatch.app's own copy of the panel is a window too
    app = "/Users/dev/Desktop/ComplianceWatch.app/Contents/Resources/control-panel/control_panel.py"
    assert core.control_panels(core.parse_ps(f"96000 1 96000 00:01 .venv/bin/python {app}\n"))


def test_a_stop_signals_the_group_only_when_every_member_is_the_checkout_s() -> None:
    state = snapshot()
    # The panel's own worker: its session holds nothing else
    assert core.stop_target(90100, state) == core.StopTarget(
        "group", 90100, (90100, 90101, 90102, 90103)
    )
    # The web app the older panel started in a session of its own
    assert core.stop_target(76174, state) == core.StopTarget("group", 76165, (76165, 76174, 76180))
    # Another session's make product-check: its group holds that session's shell, so the tree
    assert core.stop_target(8750, state) == core.StopTarget("tree", 8555, (8750, 8752, 8755, 8756))
    # A service in the older panel's group: never the group, which holds that window
    assert core.stop_target(76074, state) == core.StopTarget("tree", 75978, (76074, 76107))


def test_a_stop_describes_each_process_it_signals() -> None:
    state = snapshot()
    text = core.describe_stop(core.stop_target(8750, state), state, REPO)
    assert text.splitlines() == [
        "Send SIGTERM to pid 8750 and its children (4):",
        "  8750  make product-check  [other]",
        "  8752  bash -c env0=$(export -p); uv run --package compliancewatch-demo cw  [other]",
        "  8755  uv run --package compliancewatch-demo cw-product check  [other]",
        "  8756  cw-product check  [other]",
    ]


def test_short_commands_drop_the_checkout_and_the_interpreter() -> None:
    procs = core.parse_ps(PS)
    assert core.short_command(procs[8675].command, REPO) == "cw-mvp serve"
    assert core.short_command(procs[76165].command, REPO) == "pnpm --filter web dev"
    assert core.short_command(procs[75978].command, REPO) == "control_panel.py"
    assert core.short_command(procs[8750].command, REPO) == "make product-check"
    assert core.short_command("x" * 200, REPO, 20) == "x" * 19 + "…"
    assert core.short_command(f"{REPO}/.venv/bin/python -m pytest -q", REPO) == "pytest -q"


def test_ancestors_and_descendants_follow_the_parent_links() -> None:
    procs = core.parse_ps(PS)
    assert core.ancestors(8756, procs) == [8755, 8752, 8750, 8555, 6842, 6841, 1174]
    assert sorted(core.descendants(8750, procs)) == [8752, 8755, 8756]


LSOF_LISTEN = """\
p596
cControlCenter
f9
n*:7000
f10
n*:7000
p804
cmongod
f9
n127.0.0.1:27017
f10
n[::1]:27017
p7936
cssh
f12
n*:5432
f16
n*:19092
p8675
cpython3.12
f3
n127.0.0.1:8000
f4
n127.0.0.1:8080
p76180
cnode
f13
n*:3000
"""


def test_listeners_parse_once_per_pid_and_port() -> None:
    listeners = core.parse_lsof_listen(LSOF_LISTEN)
    assert [(item.pid, item.port) for item in listeners] == [
        (596, 7000),
        (804, 27017),
        (7936, 5432),
        (7936, 19092),
        (8675, 8000),
        (8675, 8080),
        (76180, 3000),
    ]
    assert listeners[1] == core.Listener(804, "mongod", "127.0.0.1", 27017)
    state = core.ProcessSnapshot({}, {}, frozenset(), {}, tuple(listeners), SELF, 0.0)
    assert state.listener_on(8080) == core.Listener(8675, "python3.12", "127.0.0.1", 8080)
    assert state.listener_on(3400) is None


def test_pid_files_are_read_by_name_and_owner(tmp_path: Path) -> None:
    (tmp_path / "var" / "web-stack").mkdir(parents=True)
    (tmp_path / "var" / "product").mkdir(parents=True)
    (tmp_path / "var" / "web-stack" / "identity.pid").write_text("76074\n")
    (tmp_path / "var" / "web-stack" / "web.pid").write_text("76165\n")
    (tmp_path / "var" / "web-stack" / "broken.pid").write_text("not a pid\n")
    (tmp_path / "var" / "product" / "app.pid").write_text("8662")
    (tmp_path / "var" / "product" / "web.pid").write_text("8700")
    assert core.pid_files(tmp_path / "var" / "web-stack") == {"identity": 76074, "web": 76165}
    # Only var/web-stack's web.pid is the panel's web app; var/product's is make product's
    assert core.pid_file_owners(tmp_path) == {
        8662: "make product",
        8700: "make product",
        76074: "make web-stack",
        76165: "panel web app",
    }


def test_a_group_that_holds_more_than_the_process_offers_both_stops() -> None:
    lines = (
        "90201     1 90200    00:19 uv run --package compliancewatch-identity uvicorn id:app\n"
        "90202 90201 90200    00:19 /Users/dev/cw/.venv/bin/python -m uvicorn identity:app\n"
        "90203     1 90200    00:19 uv run --package compliancewatch-qa uvicorn qa:app\n"
        "90204 90203 90200    00:19 /Users/dev/cw/.venv/bin/python -m uvicorn qa:app\n"
    )
    procs = core.parse_ps(PS + lines)
    names = core.parse_lsof_cwd(
        CWD + "".join(f"p{pid}\ncpython3.12\nfcwd\nn{REPO}\n" for pid in range(90201, 90205))
    )
    project = core.project_pids(procs, names, REPO)
    assert {90201, 90202, 90203, 90204} <= project
    origins = core.process_origins(procs, project, {90100, 90200}, PID_FILES, SELF)
    state = core.ProcessSnapshot(procs, names, frozenset(project), origins, (), SELF, 0.0)
    # make web-stack started every service in one group: the group, or this service alone
    assert core.stop_options(90201, state) == [
        core.StopTarget("group", 90200, (90201, 90202, 90203, 90204)),
        core.StopTarget("tree", 90200, (90201, 90202)),
    ]
    # A group that holds nothing but the process's own tree is one stop
    assert core.stop_options(90100, state) == [
        core.StopTarget("group", 90100, (90100, 90101, 90102, 90103))
    ]
    assert core.stop_options(SELF, state)[0].refused


def test_an_editor_that_names_the_checkout_is_not_one_of_its_processes() -> None:
    editor = "/Applications/Visual Studio Code.app/Contents/MacOS/Electron /Users/dev/cw"
    assert not core.is_project_root("Electron", editor, "/", str(REPO))
    helper = "Code Helper (Plugin) --type=utility /Users/dev/cw"
    assert not core.is_project_root("Code Helper (Plu", helper, str(REPO), str(REPO))
    # The repo's Python started from another directory is still the checkout's
    venv = "/Users/dev/cw/.venv/bin/python /tmp/script.py"
    assert core.is_project_root("python3.12", venv, "/tmp", str(REPO))
    # A program that only names the checkout from elsewhere is not
    assert not core.is_project_root("vim", "vim /Users/dev/cw/Makefile", "/Users/dev", str(REPO))


@pytest.mark.parametrize(
    ("name", "command", "cwd"),
    [
        # An agent's MCP servers, started in the checkout by Claude Code
        ("uvx", "uvx mcp-server-fetch", str(REPO)),
        ("uv", "uv tool run mcp-server-git --repository /Users/dev/cw", str(REPO)),
        (
            "node",
            "node /Users/dev/.npm/_npx/9f1e/node_modules/.bin/mcp-server-playwright",
            str(REPO),
        ),
        # Claude Code installed with pnpm: the word pnpm is on its line, its script is not ours
        ("node", "node /Users/dev/Library/pnpm/global/5/node_modules/claude/cli.js", str(REPO)),
        # A process title node rewrote, of a tool that is not the checkout's
        ("node", "npm exec @wonderwhy-er/desktop-commander@latest", str(REPO)),
        # A worktree an agent made under the checkout
        ("python3.12", "/Users/dev/cw/.claude/worktrees/x/.venv/bin/python -m pytest", "/tmp"),
        ("gnumake", "make check", "/Users/dev/cw/.claude/worktrees/x"),
        ("uv", "uv run pytest", "/Users/dev/cw/.claude/worktrees/x/services/qa"),
    ],
)
def test_agents_their_tools_and_worktrees_are_not_the_checkout_s(
    name: str, command: str, cwd: str
) -> None:
    assert not core.is_project_root(name, command, cwd, str(REPO))


@pytest.mark.parametrize(
    ("name", "command", "cwd"),
    [
        ("node", "node /opt/homebrew/bin/pnpm --filter web dev", str(REPO)),
        ("node", "node /Users/dev/cw/apps/web/node_modules/.bin/../next/dist/bin/next dev", "/"),
        ("node", "node --max-old-space-size=4096 scripts/seed.mjs", "/Users/dev/cw/apps/web"),
        ("uv", "uv run --package compliancewatch-mvp cw-mvp serve", str(REPO)),
        ("gnumake", "make check", str(REPO)),
        ("python3.12", "/Users/dev/cw/.venv/bin/python -m pytest", "/tmp"),
    ],
)
def test_the_checkout_s_own_tools_still_count(name: str, command: str, cwd: str) -> None:
    assert core.is_project_root(name, command, cwd, str(REPO))


WEB_PRODUCT = """\
 9000  6850  9000    05:00 /usr/bin/make product WEB_PORT=3000
 9010     1  9000    04:50 uv run --package compliancewatch-mvp cw-mvp serve
 9011  9010  9000    04:50 /Users/dev/cw/.venv/bin/python /Users/dev/cw/.venv/bin/cw-mvp serve
 9020     1  9000    04:50 uv run --package compliancewatch-mvp cw-mvp worker
 9021  9020  9000    04:50 /Users/dev/cw/.venv/bin/python /Users/dev/cw/.venv/bin/cw-mvp worker
 9030     1  9000    04:49 node /opt/homebrew/bin/pnpm --filter web dev
 9031  9030  9000    04:49 node /Users/dev/cw/apps/web/node_modules/.bin/../next/dist/bin/next dev
 9032  9031  9000    04:48 next-server (v16.3.8)
 9033  9032  9000    04:48 node /Users/dev/cw/apps/web/.next/dev/build/chunks/pool_entry.js 58165
"""


def web_project(repo: Path) -> core.Project:
    return core.Project(
        repo=repo,
        env=core.program_env({"PATH": "/usr/bin"}),
        ports=core.resolve_ports({}, {}),
        make_targets={},
        checks=[],
        check_steps=[],
        screens=[],
        workers=[],
        relays=[],
    )


def test_stop_web_app_ends_the_web_app_s_tree_and_not_the_product_beside_it(
    tmp_path: Path,
) -> None:
    # A terminal's make product with its web app on 3000: one process group holds the product's
    # app, its worker and the web app, so a group stop would end the product too
    procs = core.parse_ps(WEB_PRODUCT)
    cwds = {pid: str(REPO) for pid in procs}
    cwds.update({9031: f"{REPO}/apps/web", 9032: f"{REPO}/apps/web", 9033: f"{REPO}/apps/web"})
    names = {pid: ("gnumake" if pid == 9000 else "node", cwd) for pid, cwd in cwds.items()}
    names.update({9010: ("uv", str(REPO)), 9020: ("uv", str(REPO))})
    names.update({9011: ("python3.12", str(REPO)), 9021: ("python3.12", str(REPO))})
    project = core.project_pids(procs, names, REPO)
    assert set(procs) <= project | {6850}
    listener = core.Listener(9032, "node", "*", 3000)
    origins = core.process_origins(procs, project, set(), {}, SELF)
    state = core.ProcessSnapshot(procs, names, frozenset(project), origins, (listener,), SELF, 0.0)
    assert core.stop_target(9032, state).mode == "group"  # what the old stop sent SIGTERM to
    assert core.web_app_root(9032, state) == 9030
    targets, notes = core.web_stop_targets(web_project(tmp_path), state)
    assert targets == [core.StopTarget("tree", 9000, (9030, 9031, 9032, 9033))]
    assert notes == []
    assert core.describe_stop(targets[0], state, REPO).splitlines()[0] == (
        "Send SIGTERM to pid 9030 and its children (4):"
    )


def test_stop_web_app_reads_the_panel_s_pid_file_and_names_what_it_leaves(
    tmp_path: Path,
) -> None:
    state = snapshot()
    project = web_project(tmp_path)
    project.web().pid_file.parent.mkdir(parents=True)
    project.web().pid_file.write_text("76165\n")
    listener = core.Listener(76180, "node", "*", 3000)
    with_port = core.ProcessSnapshot(
        state.procs, state.names, state.project, state.origins, (listener,), SELF, 0.0
    )
    # The recorded web app and the listener are one tree, reached once
    targets, notes = core.web_stop_targets(project, with_port)
    assert targets == [core.StopTarget("tree", 76165, (76165, 76174, 76180))]
    assert notes == []
    # A pid file whose pid runs another program, and a port held outside the checkout
    project.web().pid_file.write_text("8750\n")
    stranger = core.Listener(596, "ControlCenter", "*", 3000)
    elsewhere = core.ProcessSnapshot(
        state.procs, state.names, state.project, state.origins, (stranger,), SELF, 0.0
    )
    assert core.web_stop_targets(project, elsewhere) == (
        [],
        [
            "var/web-stack/web.pid names pid 8750, which is not the web app",
            "port 3000 is held by pid 596, which is not this checkout's",
        ],
    )


def test_a_stop_s_confirm_names_the_other_sessions_it_breaks() -> None:
    state = snapshot()
    users = core.stack_users(state, REPO)
    check = "make product-check (pid 8750, 28 s) with 3 more"
    assert users.product == (check,)
    assert users.docker == (check,)
    note = core.breaks_note(users, docker=True, product=True)
    assert f"Stopping Docker will break them:\n  {check}" in note
    assert f"Stopping the product will break them:\n  {check}" in note
    # another control panel window only reads: it breaks nothing and is not named
    assert "control panel" not in note
    assert core.breaks_note(users) == ""
    assert core.breaks_note(core.StackUsers((), ()), docker=True, product=True) == ""


def test_another_session_s_tests_are_named_before_docker_stops() -> None:
    pytest_run = core.Proc(5000, 4990, 5000, 171, f"{REPO}/.venv/bin/python -m pytest -q tests")
    editor = core.Proc(5100, 4990, 5100, 900, f"{REPO}/.venv/bin/ruff server")
    state = core.ProcessSnapshot(
        {5000: pytest_run, 5100: editor},
        {},
        frozenset({5000, 5100}),
        {5000: "other", 5100: "other"},
        (),
        SELF,
        0.0,
    )
    users = core.stack_users(state, REPO)
    assert len(users.docker) == 1
    assert users.docker == ("pytest -q tests (pid 5000, 2m 51s)",)
    assert users.product == ()
    note = core.breaks_note(users, docker=True, product=True)
    assert note.startswith("Other sessions are using Docker's databases and queues")
    assert "Stopping Docker will break them" in note
    assert "ruff" not in note


def test_a_make_target_that_needs_no_docker_is_not_named() -> None:
    lint = core.Proc(6000, 5990, 6000, 30, "/usr/bin/make lint")
    eslint = core.Proc(6001, 6000, 6000, 29, "node /Users/dev/cw/node_modules/.bin/pnpm lint")
    check = core.Proc(6100, 5990, 6100, 40, "/usr/bin/make check")
    state = core.ProcessSnapshot(
        {proc.pid: proc for proc in (lint, eslint, check)},
        {},
        frozenset({6000, 6001, 6100}),
        {6000: "other", 6001: "other", 6100: "other"},
        (),
        SELF,
        0.0,
    )
    users = core.stack_users(state, REPO)
    assert users.docker == ("make check (pid 6100, 40 s)",)
    assert users.product == ()
