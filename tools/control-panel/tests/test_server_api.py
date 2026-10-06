"""Every route of API.md against the demo core: the shapes the UI reads, previews and their
confirm tokens, runs that stream and cancel, and the reads beside them."""

import time
from collections.abc import Iterator
from typing import Any

import panel_demo as demo
import panel_server as server
import pytest
from serverkit import Served

ACTION_KEYS = {
    "id",
    "title",
    "summary",
    "what_happens",
    "duration",
    "group",
    "safety",
    "needs_confirm",
    "preview",
    "confirm",
    "enabled",
    "reason",
    "fix_action",
    "kind",
    "button",
    "params",
    "steps",
    "command",
    "url",
    "source",
    "covered_by",
    "keywords",
    "calls_model",
}
RUN_KEYS = {
    "run_id",
    "action_id",
    "title",
    "kind",
    "params",
    "state",
    "started_at",
    "finished_at",
    "seconds",
    "current_step",
    "steps",
    "error",
}


@pytest.fixture
def served() -> Iterator[Served]:
    with Served() as running:
        running.demo({"speed": 20})
        yield running


def test_meta_and_status_have_their_shapes(served: Served) -> None:
    meta = served.get("/api/meta").json
    assert meta["api"] == server.API_VERSION
    assert meta["demo"] is True
    assert set(meta) == {"api", "demo", "build", "repo", "started_at"}
    status = served.get("/api/status").json
    assert {
        "taken_at",
        "loading",
        "demo",
        "summary",
        "level",
        "docker",
        "infra",
        "services",
        "web",
        "product",
        "background",
        "checkout",
        "sessions",
        "warnings",
    } <= set(status)
    assert status["level"] in ("running", "partial", "stopped", "unknown")
    assert len(status["services"]) == 10
    assert set(status["product"]) == {"internal", "public", "worker", "web", "pids", "llm_provider"}
    for warning in status["warnings"]:
        assert set(warning) == {"code", "tone", "title", "message", "items"}


def test_the_catalog_lists_every_action_with_plain_words(served: Served) -> None:
    catalog = served.get("/api/actions").json
    assert [group["id"] for group in catalog["groups"]][:2] == ["everything", "docker"]
    actions = {action["id"]: action for action in catalog["actions"]}
    for action in actions.values():
        assert set(action) == ACTION_KEYS, action["id"]
        assert all((action["title"], action["summary"], action["duration"])), action["id"]
        assert action["safety"] in (
            "safe",
            "changes-data",
            "stops-things",
            "destructive",
            "refused",
        )
        assert (
            action["preview"]
            == action["needs_confirm"]
            == (
                action["safety"] in ("changes-data", "stops-things", "destructive")
                or action["calls_model"]
            )
        )
        if action["safety"] == "refused":
            assert action["enabled"] is False
            assert action["reason"]
        if not action["enabled"]:
            assert action["reason"]
        assert isinstance(action["command"], str)
    for curated in (
        "start-everything",
        "stop-everything",
        "force-stop-docker",
        "reset",
        "open-doc",
    ):
        assert actions[curated]["source"] == "curated"
    assert actions["make:backfill"]["safety"] == "refused"
    assert actions["stop-everything"]["command"].count("\n") >= 2  # one program per line


def test_a_safe_action_runs_at_once_and_streams_its_steps(served: Served) -> None:
    preview = served.preview("backup")
    assert preview["confirm"] is None
    assert preview["confirm_token"] is None
    stream = served.events()
    stream.until("hello")
    reply = served.post("/api/actions/backup/run", {"params": {}})
    assert reply.status == 202
    run_id = reply.json["run_id"]
    started = stream.until("run.started")
    assert started.data["run_id"] == run_id
    assert set(started.data) == {
        "run_id",
        "action_id",
        "title",
        "kind",
        "steps",
        "started_at",
        "params",
    }
    output = stream.until("run.output")
    assert output.data["lines"][0]["text"].startswith("▸ ")
    finished = stream.until("run.finished")
    assert finished.data["state"] == "ok"
    assert finished.data["finished_at"] >= started.data["started_at"]
    toast = stream.until("toast")
    assert toast.data["run_id"] == run_id
    detail = served.finished(run_id)
    assert RUN_KEYS | {"lines"} == set(detail)
    assert detail["state"] == "ok"
    assert [step["state"] for step in detail["steps"]] == ["ok"]
    listed = served.get("/api/runs?limit=5").json["runs"]
    assert listed[0]["run_id"] == run_id
    assert set(listed[0]) == RUN_KEYS


def test_a_risky_action_needs_its_preview_s_token_once(served: Served) -> None:
    served.demo({"world": {"docker": True, "infra": True}})
    without = served.post("/api/actions/databases-stop/run", {"params": {}})
    assert without.status == 428
    assert without.error["code"] == "confirm-required"
    preview = served.preview("databases-stop")
    confirm = preview["confirm"]
    assert set(confirm) == {
        "title",
        "text",
        "what_happens",
        "warnings",
        "button",
        "details",
        "reaches",
    }
    assert preview["expires_in"] == int(server.CONFIRM_SECONDS)
    token = preview["confirm_token"]
    first = served.post("/api/actions/databases-stop/run", {"params": {}, "confirm_token": token})
    assert first.status == 202
    served.finished(first.json["run_id"])
    again = served.post("/api/actions/databases-stop/run", {"params": {}, "confirm_token": token})
    assert again.status == 428


def test_a_token_is_bound_to_its_parameters_and_confirm_is_its_other_name(served: Served) -> None:
    served.demo({"world": {"docker": True, "infra": True}})
    token = served.preview("migrate", {"service": "identity"})["confirm_token"]
    other = served.post(
        "/api/actions/migrate/run", {"params": {"service": "rulebook"}, "confirm_token": token}
    )
    assert other.status == 428
    token = served.preview("migrate", {"service": "identity"})["confirm_token"]
    ok = served.post(
        "/api/actions/migrate/run", {"params": {"service": "identity"}, "confirm": token}
    )
    assert ok.status == 202
    served.finished(ok.json["run_id"])


def test_an_empty_optional_choice_means_not_given(served: Served) -> None:
    served.demo({"world": {"docker": True, "infra": True}})
    preview = served.preview("migrate", {"service": ""})
    assert preview["params"] == {"service": None}
    assert preview["steps"] == ["make migrate"]
    run = served.post(
        "/api/actions/migrate/run",
        {"params": {"service": ""}, "confirm_token": preview["confirm_token"]},
    )
    assert run.status == 202
    served.finished(run.json["run_id"])


def test_wrong_parameters_unknown_actions_and_refusals(served: Served) -> None:
    served.demo({"world": {"docker": True, "infra": True}})
    unknown = served.post("/api/actions/migrate/preview", {"params": {"service": "nope"}})
    assert unknown.status == 400
    assert unknown.error["code"] == "bad-params"
    extra = served.post("/api/actions/backup/preview", {"params": {"ARGS": "--destructive"}})
    assert extra.status == 400
    assert served.post("/api/actions/no-such-thing/preview").status == 404
    refused = served.post("/api/actions/make:backfill/run", {"params": {}})
    assert refused.status == 403
    assert refused.error["code"] == "refused"
    assert served.post("/api/actions/make:backfill/preview").status == 403
    rollback = served.post("/api/actions/product-check/preview", {"params": {"step": "rollback"}})
    assert rollback.status in (400, 403)


def test_an_action_that_needs_docker_says_so_before_it_is_pressed(served: Served) -> None:
    served.demo({"reset": True})
    actions = {a["id"]: a for a in served.get("/api/actions").json["actions"]}
    assert actions["databases-start"]["enabled"] is False
    assert actions["databases-start"]["reason"] == "Docker is not running."
    assert actions["databases-start"]["fix_action"] == "docker-start"
    assert actions["product-seed"]["enabled"] is False
    assert actions["product-seed"]["fix_action"] == "product-start"
    disabled = served.post("/api/actions/databases-start/run", {"params": {}})
    assert disabled.status == 403
    assert disabled.error["code"] == "disabled"
    assert disabled.error["action"] == "docker-start"
    assert served.app.runs.recent(5) == []


def test_one_step_runs_at_a_time_and_cancel_stops_it(served: Served) -> None:
    served.demo({"speed": 0.5, "world": {"docker": True, "infra": True}})
    run_id = served.start("start-everything")
    busy = served.post("/api/actions/backup/run", {"params": {}})
    assert busy.status == 409
    assert busy.error["code"] == "busy"
    assert served.post(f"/api/runs/{run_id}/cancel").json == {"ok": True}
    detail = served.finished(run_id)
    assert detail["state"] == "cancelled"
    assert "cancelled" in [step["state"] for step in detail["steps"]]
    late = served.post(f"/api/runs/{run_id}/cancel")
    assert late.status == 409
    assert late.error["code"] == "not-running"
    assert served.post("/api/runs/r999/cancel").status == 404
    assert served.get("/api/runs/r999").status == 404


def test_a_failed_run_says_why_in_plain_words(served: Served) -> None:
    served.demo({"reset": True, "world": {"docker": True, "infra": True}})
    served.demo(
        {
            "fail_next": {
                "action": "backup",
                "lines": ["Cannot connect to the Docker daemon at unix:///var/run/docker.sock."],
            }
        }
    )
    detail = served.finished(served.start("backup"))
    assert detail["state"] == "failed"
    assert detail["error"]["code"] == "docker-down"
    assert detail["error"]["action"] == "docker-start"
    assert detail["error"]["message"]


def test_the_stops_name_the_pids_they_reach(served: Served) -> None:
    served.demo({"world": {"docker": True, "infra": True, "web": True, "sessions": "agent"}})
    served.app.on_probe("processes", served.backend.probe_processes())
    preview = served.preview("web-stop")
    reaches = preview["reaches"]
    assert reaches == preview["confirm"]["reaches"]
    assert {item["pid"] for item in reaches} >= {76165}
    assert all(set(item) == {"pid", "command", "origin"} for item in reaches)
    stop_all = served.preview("stop-everything")
    codes = [warning["code"] for warning in stop_all["confirm"]["warnings"]]
    assert "sessions" in codes
    sessions = next(w for w in stop_all["confirm"]["warnings"] if w["code"] == "sessions")
    assert sessions["tone"] == "danger"
    assert sessions["items"]


def test_a_branch_that_is_not_main_warns_before_a_change(served: Served) -> None:
    served.demo({"world": {"docker": True, "infra": True, "branch": "pipeline-ops"}})
    warnings = served.preview("migrate")["confirm"]["warnings"]
    branch = next(w for w in warnings if w["code"] == "not-main")
    assert branch["tone"] == "danger"
    assert "shared development database" in branch["message"]
    status = served.get("/api/status").json
    assert status["checkout"]["is_main"] is False
    assert status["warnings"][0]["code"] == "not-main"


def test_open_actions_and_documents_open_at_once(served: Served) -> None:
    opened = served.post("/api/actions/open-env/run", {"params": {}})
    assert opened.status == 200
    assert opened.json["ok"] is True
    assert opened.json["target"].endswith("/.env")
    docs = served.get("/api/docs").json["docs"]
    assert docs
    assert set(docs[0]) == {"id", "label", "path", "kind", "action", "params"}
    doc = served.post(f"/api/docs/{docs[0]['id']}/open")
    assert doc.json["opened"] is True
    assert served.post("/api/docs/nope/open").status == 404
    by_action = served.post("/api/actions/open-doc/run", {"params": {"doc": docs[0]["id"]}})
    assert by_action.status == 200


def test_processes_and_their_stop_need_a_preview(served: Served) -> None:
    served.demo({"world": {"docker": True, "infra": True, "web": True}})
    served.app.on_probe("processes", served.backend.probe_processes())
    listing = served.get("/api/processes").json
    assert {"taken_at", "ports", "processes", "error"} <= set(listing)
    pid = next(p["pid"] for p in listing["processes"] if "pnpm" in p["command"])
    preview = served.get(f"/api/processes/{pid}/stop-preview").json
    assert preview["pid"] == pid
    assert preview["confirm_token"]
    for warning in preview["warnings"]:
        assert set(warning) == {"code", "tone", "title", "message", "items"}
    modes = [option["mode"] for option in preview["options"] if not option["refused"]]
    blind = served.post(f"/api/processes/{pid}/stop", {"mode": modes[0]})
    assert blind.status == 428
    stop = served.post(
        f"/api/processes/{pid}/stop", {"mode": modes[0], "confirm_token": preview["confirm_token"]}
    )
    assert stop.status == 202
    served.finished(stop.json["run_id"])
    bad = served.post(f"/api/processes/{pid}/stop", {"mode": "everything"})
    assert bad.status == 400


def test_this_app_and_claude_code_are_never_offered_a_stop(served: Served) -> None:
    served.demo({"world": {"sessions": "agent"}})
    served.app.on_probe("processes", served.backend.probe_processes())
    listed = {p["pid"]: p for p in served.get("/api/processes").json["processes"]}
    assert {pid: listed[pid]["origin"] for pid in demo.AGENT_PIDS} == dict.fromkeys(
        demo.AGENT_PIDS, "run by Claude Code"
    )
    guarded = served.get("/api/processes/61002/stop-preview").json
    assert {option["refused"] for option in guarded["options"]} == {
        "Claude Code runs it; stop it there"
    }
    for pid in (demo.DEMO_PID, 6842, *demo.AGENT_PIDS):
        preview = served.get(f"/api/processes/{pid}/stop-preview")
        body = preview.json
        assert preview.status == 200
        assert body["confirm_token"] is None
        assert all(option["refused"] for option in body["options"])
        stop = served.post(f"/api/processes/{pid}/stop", {"mode": "tree"})
        assert stop.status == 428
    assert served.get("/api/processes/999999/stop-preview").status == 404


def test_the_reads_beside_the_runs(served: Served) -> None:
    flags = served.get("/api/flags").json
    assert flags["error"] == ""
    assert {"name", "value", "default", "env"} <= set(flags["flags"][0])
    sources = served.get("/api/logs").json["sources"]
    assert all(set(s) == {"id", "label", "group", "path", "kind", "available"} for s in sources)
    log = served.get(f"/api/logs/{sources[0]['id']}?tail=5").json
    assert len(log["lines"]) == 5
    assert served.get("/api/logs/nope").status == 404
    assert served.get("/api/heartbeat").status == 405
    assert served.post("/api/heartbeat").json == {"ok": True, "idle_exit_in": 600}


def test_a_quick_first_read_answers_at_once(served: Served) -> None:
    first = served.get("/api/features").json
    assert first["loading"] is False
    features = first["features"]
    assert {f["state"] for f in features} <= {"live", "not-running", "not-built", "error"}
    assert {"id", "title", "summary", "state", "numbers", "links", "note", "source"} <= set(
        features[0]
    )
    github = served.get("/api/github").json
    assert github["loading"] is False
    assert github["available"] is True
    assert {pr["checks"] for pr in github["prs"]} <= {"passing", "failing", "pending", "none"}


class SlowFeatures(demo.DemoBackend):
    def features(self, status: Any, last_check: Any) -> list[dict[str, Any]]:
        time.sleep(server.FIRST_READ_SECONDS + 0.5)
        return super().features(status, last_check)


def test_a_slow_read_lands_later_with_an_event() -> None:
    with Served(SlowFeatures(pace=0.01)) as served:
        stream = served.events()
        stream.until("hello")
        first = served.get("/api/features").json
        assert first == {"features": [], "loading": True, "reading": True}
        stream.until("features")
        later = served.get("/api/features").json
        assert later["loading"] is False
        assert later["features"]


def test_kafka_reads_only_when_asked_and_at_most_every_30_seconds(served: Served) -> None:
    served.demo({"world": {"docker": True, "infra": True}})
    before = served.get("/api/kafka").json
    assert before["taken_at"] is None
    stream = served.events()
    stream.until("hello")
    assert served.post("/api/kafka/refresh").json == {"started": True, "next_in": 30}
    landed = stream.until("kafka")
    assert landed.data["groups"]
    assert landed.data["error"] == ""
    again = served.post("/api/kafka/refresh").json
    assert again["started"] is False
    assert 0 < again["next_in"] <= 30


def test_prefs_take_their_own_keys_only(served: Served) -> None:
    assert served.get("/api/prefs").json == {"tour_done": False, "last_view": "", "dismissed": []}
    saved = served.request("PUT", "/api/prefs", {"tour_done": True, "last_view": "run"})
    assert saved.json == {"tour_done": True, "last_view": "run", "dismissed": []}
    for bad in ({"theme": "dark"}, {"tour_done": "yes"}, {"last_view": "../x"}):
        assert served.request("PUT", "/api/prefs", bad).status == 400
    assert served.get("/api/prefs").json["tour_done"] is True


def test_prefs_are_kept_in_their_file(tmp_path: server.Path) -> None:
    path = tmp_path / "prefs" / "prefs.json"
    prefs = server.Prefs(path)
    assert prefs.get()["tour_done"] is False
    prefs.update({"tour_done": True})
    assert server.Prefs(path).get()["tour_done"] is True
    path.write_text("not json")
    assert server.Prefs(path).get() == dict(server.DEFAULT_PREFS)


def test_the_summary_is_plain_english() -> None:
    def status(**up: bool) -> server.core.Status:
        return server.core.Status(
            True,
            {
                name: server.core.Container(name, "running", "healthy", "Up", 0, ())
                for name in server.core.INFRA
            },
            up,
            {},
            {},
            0.0,
        )

    assert server.summarize(status()) == (
        "partial",
        "The databases are running; the services and the web app are stopped.",
    )
    assert server.summarize(status(web=True))[1] == (
        "The databases and the web app are running; the services are stopped."
    )


@pytest.mark.parametrize(
    ("line", "code"),
    [
        ("Cannot connect to the Docker daemon at unix:///var/run/docker.sock", "docker-down"),
        (
            "curl: (7) Failed to connect to 127.0.0.1 port 8080 after 0 ms: Connection refused",
            ("product-down"),
        ),
        (
            'psycopg.OperationalError: connection to server at "127.0.0.1", port 5432 failed: '
            "Connection refused",
            "databases-down",
        ),
        ("httpx.ConnectError: [Errno 61] Connection refused", "failed"),
        ("error: refused: make backfill: make backfill is never run here", "refused"),
        ("error: rulebook worker refused: runs sh", "refused"),
        (
            "pipeline-extract-backlog: refused: CW_PIPELINE_EXTRACTION_ENABLED is off",
            ("extraction-off"),
        ),
        ("the gateway refused the request: 429", "failed"),
        ("error: changed since the question: 2 processes were left alone", "changed"),
    ],
)
def test_a_failure_is_named_by_what_went_wrong(line: str, code: str) -> None:
    assert server.classify_failure(["▸ a step", line], timed_out=False)["code"] == code
