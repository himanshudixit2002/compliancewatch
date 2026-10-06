"""The ``--demo`` core: runs that play out and change the made-up world, its own error paths,
and ``POST /api/demo/state``, which the UI's tests use to set the world."""

from collections.abc import Iterator

import panel_demo as demo
import panel_server as server
import pytest
from serverkit import Served, wait_for


@pytest.fixture
def served() -> Iterator[Served]:
    with Served() as running:
        running.demo({"reset": True, "speed": 20})
        yield running


def status(served: Served) -> dict[str, object]:
    return dict(served.get("/api/status").json)


def test_the_demo_runs_nothing_real() -> None:
    backend = demo.DemoBackend()
    runner = backend.make_runner("steps", lambda event: None)
    assert isinstance(runner, demo.DemoRunner)
    assert not hasattr(runner, "execute")
    assert backend.demo is True
    assert backend.open_psql().endswith("(demo: nothing opened)")


def test_reset_gives_the_tests_world(served: Served) -> None:
    body = status(served)
    assert body["level"] == "stopped"
    assert body["sessions"] == []
    assert body["warnings"] == []
    checkout = body["checkout"]
    assert isinstance(checkout, dict)
    assert checkout["is_main"] is True
    world = served.demo({})["world"]
    assert world["docker"] is False
    assert world["services"] == 0
    assert world["fail_next"] is None
    assert world["mishaps"] is False


def test_the_world_can_be_set_part_by_part(served: Served) -> None:
    stream = served.events()
    stream.until("status")
    answer = served.demo(
        {
            "world": {
                "docker": True,
                "infra": True,
                "services": 4,
                "product": {"internal": True},
                "branch": "pipeline-ops",
                "sessions": "agent",
                "workers": ["pipeline"],
            }
        }
    )
    assert answer["ok"] is True
    while (pushed := stream.until("status").data)["checkout"]["branch"] != "pipeline-ops":
        pass  # the stream sees the new world without asking
    assert pushed["sessions"]
    body = status(served)
    services = body["services"]
    assert isinstance(services, list)
    assert sum(1 for service in services if service["up"]) == 4
    product = body["product"]
    assert isinstance(product, dict)
    assert {part: product[part]["up"] for part in ("internal", "public", "worker", "web")} == {
        "internal": True,
        "public": False,
        "worker": False,
        "web": False,
    }
    sessions = body["sessions"]
    assert isinstance(sessions, list)
    assert [session["kind"] for session in sessions] == ["agent"]
    background = body["background"]
    assert isinstance(background, list)
    running = [item["key"] for item in background if item["pid"]]
    assert running == ["worker-pipeline"]
    served.demo({"world": {"product": {"public": True}}})  # merged, as the mock does
    product = status(served)["product"]
    assert isinstance(product, dict)
    assert product["internal"]["up"]
    assert product["public"]["up"]


def test_a_wrong_body_changes_nothing(served: Served) -> None:
    before = served.demo({})["world"]
    for body in (
        {"world": {"docker": "yes"}},
        {"world": {"services": 11}},
        {"world": {"product": {"kitchen": True}}},
        {"world": {"branch": "main; rm -rf /"}},
        {"world": {"sessions": "everyone"}},
        {"world": {"docker": True}, "fail_next": {"action": "no-such-action"}},
        {"fail_next": {"action": "backup", "state": "exploded"}},
        {"speed": 0},
        {"prefs": {"theme": "dark"}},
        {"reset": "please"},
        {"surprise": True},
    ):
        reply = served.post("/api/demo/state", body)
        assert reply.status == 400, body
        assert reply.error["code"] == "bad-params"
    assert served.demo({})["world"] == before


def test_it_exists_only_in_the_demo() -> None:
    backend = demo.DemoBackend()
    backend.demo = False  # a core that is not the demo's
    with Served(backend) as served:
        assert served.post("/api/demo/state", {"reset": True}).status == 404
    assert isinstance(demo.DemoBackend(), server.DemoControl)


def test_a_failure_can_be_armed_for_the_next_run(served: Served) -> None:
    served.demo({"world": {"docker": True, "infra": True}})
    served.demo(
        {
            "failNext": {
                "action": "docker-stop",
                "step": 0,
                "state": "timeout",
                "lines": ["waiting for the VM to stop..."],
            }
        }
    )
    run = served.finished(served.start("docker-stop"))
    assert run["state"] == "failed"
    assert run["steps"][0]["state"] == "timeout"
    assert run["error"]["action"] == "force-stop-docker"
    assert run["error"]["message"] == "Docker did not stop in time"
    assert "waiting for the VM to stop..." in [line["text"] for line in run["lines"]]
    assert served.demo({})["world"]["fail_next"] is None  # used once
    again = served.finished(served.start("docker-stop"))
    assert again["state"] == "ok"


def test_runs_change_the_world(served: Served) -> None:
    served.finished(served.start("start-everything"))
    wait_for(lambda: status(served)["level"] == "running")
    served.finished(served.start("stop-everything"))
    wait_for(lambda: status(served)["level"] == "stopped")


def test_the_demo_s_own_failures_show_until_reset() -> None:
    with Served() as served:
        served.demo({"speed": 20})
        assert served.demo({})["world"]["mishaps"] is True
        lint = served.finished(served.start("gate:lint"))
        assert lint["state"] == "failed"
        assert "✖ 1 problem (1 error, 0 warnings)" in [line["text"] for line in lint["lines"]]
        actions = {a["id"]: a for a in served.get("/api/actions").json["actions"]}
        assert actions["product-seed"]["enabled"] is False
        assert actions["product-seed"]["fix_action"] == "product-start"
        served.demo({"reset": True})
        passed = served.finished(served.start("gate:lint"))
        assert passed["state"] == "ok"
        texts = [line["text"] for line in passed["lines"]]
        assert "eslint: no problems" in texts
        assert not [text for text in texts if "error" in text.lower()]


def test_reset_cancels_and_forgets_the_runs(served: Served) -> None:
    served.demo({"speed": 0.2, "world": {"docker": True, "infra": True}})
    run_id = served.start("start-everything")
    served.demo({"reset": True})
    assert served.get("/api/runs").json["runs"] == []
    assert served.get(f"/api/runs/{run_id}").status == 404
    assert served.app.runs.current("step") is None


def test_expired_tokens_and_prefs(served: Served) -> None:
    served.demo({"world": {"docker": True, "infra": True}})
    token = served.preview("databases-stop")["confirm_token"]
    served.demo({"expire_tokens": True, "prefs": {"tour_done": True}})
    late = served.post("/api/actions/databases-stop/run", {"params": {}, "confirm_token": token})
    assert late.status == 428
    assert served.get("/api/prefs").json["tour_done"] is True
