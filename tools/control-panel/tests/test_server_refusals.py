"""The helper runs actions only through panel_core's checked runner, so its refusal rules hold
at the moment a program would start, whatever the HTTP layer let through. A stand-in checkout
whose Makefile only touches files shows what ran."""

import shutil
import time
from pathlib import Path

import panel_catalog as catalog
import panel_core as core
import panel_server as server
import pytest

MAKEFILE = """\
lint: ## Lint both sides
\ttouch ran-lint
backfill: ## Backfill every source from the live regulator sites
\ttouch ran-backfill
dev-reset: ## Drop every volume and start again
\ttouch ran-reset
product-check: ## Check the product works, step by step
\ttouch ran-check
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "Makefile").write_text(MAKEFILE)
    return checkout


@pytest.fixture
def app(repo: Path) -> server.App:
    return server.App(server.RealBackend(repo), token="x" * 43, port=1, prefs=server.Prefs(None))


def wait_idle(app: server.App) -> None:
    deadline = time.monotonic() + 20
    while app.runs.current("step") is not None:
        assert time.monotonic() < deadline
        time.sleep(0.05)


def test_a_refused_target_never_reaches_a_program(app: server.App, repo: Path) -> None:
    for action in ("make:backfill", "make:dev-reset"):
        with pytest.raises(server.ApiError) as caught:
            app.run(action, {"params": {}})
        assert caught.value.status == 403
    assert not (repo / "ran-backfill").exists()
    assert not (repo / "ran-reset").exists()


def test_a_plan_smuggled_past_the_catalog_is_refused_by_the_runner(
    app: server.App, repo: Path
) -> None:
    spec = app.catalog.specs["make:lint"]
    for plan in (
        core.Plan("x", (core.make("backfill"),)),
        core.Plan("x", (core.make("product-check", "ARGS=--destructive"),)),
        core.Plan("x", (core.Cmd("x", ("sh", "-c", "touch ran-shell")),)),
        core.Plan("x", (core.make("dev-reset"),)),  # destructive: only with its own confirm
    ):
        with pytest.raises(server.ApiError) as caught:
            app.runs.start(spec, plan, {})
        assert caught.value.status == 403
        assert caught.value.code == "refused"
        assert "refused" in caught.value.detail
    wait_idle(app)
    assert sorted(path.name for path in repo.iterdir()) == [".git", "Makefile"]
    assert app.runs.current("step") is None


def test_the_rollback_step_and_extra_arguments_are_refused(app: server.App) -> None:
    for params in ({"step": "rollback"}, {"step": "--destructive"}, {"ARGS": "x"}):
        with pytest.raises(server.ApiError) as caught:
            app.preview("product-check", {"params": params})
        assert caught.value.status in (400, 403)


@pytest.mark.skipif(shutil.which("make") is None, reason="needs make")
def test_an_allowed_action_runs_through_the_runner(app: server.App, repo: Path) -> None:
    preview = app.preview("make:lint", {"params": {}})
    body = {"params": {}, "confirm_token": preview["confirm_token"]}
    status, answer = app.run("make:lint", body)
    assert status == 202
    wait_idle(app)
    run = app.runs.get(answer["run_id"])
    assert run is not None
    assert run.state == "ok", list(run.lines)
    assert (repo / "ran-lint").exists()
    assert not (repo / "ran-backfill").exists()


def test_the_catalog_of_this_checkout_follows_its_makefile(app: server.App) -> None:
    specs = app.catalog.specs
    assert specs["make:backfill"].safety == "refused"
    assert specs["make:dev-reset"].safety == "refused"
    assert specs["gate:lint"].source == "curated"
    assert "gate:check" not in specs  # no such target in this Makefile
    assert catalog.Catalog.load(app.project).specs.keys() == specs.keys()
