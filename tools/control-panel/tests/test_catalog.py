"""The action catalog over the checkout's own Makefile: every documented target is in it, each
with plain words and a safety class; whatever the runner would refuse is refused here first,
and nothing refused can be previewed or run."""

import dataclasses
import os
from pathlib import Path

import panel_catalog as catalog
import panel_core as core
import panel_server as server
import pytest

ROOT = Path(os.environ.get(core.REPO_ENV) or Path(__file__).resolve().parents[3])
NEVER = (
    "backfill",
    "label",
    "seed",
    "run",
    "worker",
    "relay",
    "dev-reset",
    "dev-restore",
    "hooks",
    "control-panel",
    "control-panel-app",
    "web-e2e",  # on its own it tests against the person's stack: gate:web-e2e uses a test copy
)

pytestmark = pytest.mark.skipif(not (ROOT / "Makefile").is_file(), reason=f"no Makefile in {ROOT}")


@pytest.fixture(scope="module")
def project() -> core.Project:
    return core.Project.load(ROOT)


@pytest.fixture(scope="module")
def built(project: core.Project) -> catalog.Catalog:
    return catalog.Catalog.load(project)


@pytest.fixture(scope="module")
def app() -> server.App:
    """The helper's logic over the checkout, reading files only: no poller, no probe."""
    return server.App(server.RealBackend(ROOT), token="x" * 43, port=1, prefs=server.Prefs(None))


def documented(project: core.Project) -> dict[str, str]:
    return {target: text for target, text in project.make_targets.items() if text.strip()}


def test_every_documented_target_is_an_action_with_plain_words(
    project: core.Project, built: catalog.Catalog
) -> None:
    targets = documented(project)
    assert targets, "the Makefile documents no target"
    made = {spec.target for spec in built.specs.values() if spec.source == "make"}
    assert made == set(targets)
    for spec in built.specs.values():
        assert all((spec.title, spec.summary, spec.what_happens, spec.duration)), spec.id
        assert spec.safety in ("safe", "changes-data", "stops-things", "destructive", "refused")
        assert spec.group in {key for key, _ in catalog.GROUPS}
        if spec.safety == "refused":
            assert spec.refused, spec.id
        if spec.covered_by:
            assert spec.covered_by in built.specs, spec.id


def test_the_targets_that_are_never_run_here_are_refused(
    project: core.Project, built: catalog.Catalog
) -> None:
    for target in NEVER:
        if target in project.make_targets:
            assert built.specs[f"make:{target}"].safety == "refused", target


def test_what_the_runner_would_refuse_is_refused_first(
    project: core.Project, built: catalog.Catalog
) -> None:
    for target in documented(project):
        plain = core.plan_problems(core.Plan(target, (core.make(target),)), project.known_targets)
        if plain:
            assert built.specs[f"make:{target}"].safety == "refused", (target, plain)


def test_every_action_offered_passes_the_runner_s_rules(app: server.App) -> None:
    for spec in app.catalog.specs.values():
        if spec.safety == "refused" or spec.kind == "open":
            continue
        values = {
            param.name: param.default
            if param.default is not None
            else next(iter(catalog.choices(app, param)), ("", ""))[0]
            for param in spec.params
        }
        if any(
            value == "" and param.required
            for param, value in zip(spec.params, values.values(), strict=True)
        ):
            continue  # nothing to choose here (no backup yet)
        built = catalog.build(app, spec, values, expected={})
        assert built.plan is not None, spec.id
        assert core.plan_problems(built.plan, app.project.known_targets) == [], spec.id


def test_nothing_refused_can_be_previewed_or_run(app: server.App) -> None:
    refused = [spec for spec in app.catalog.specs.values() if spec.safety == "refused"]
    assert refused
    for spec in refused:
        for call in (app.preview, app.run):
            with pytest.raises(server.ApiError) as caught:
                call(spec.id, {"params": {}})
            assert caught.value.status == 403, spec.id
            assert caught.value.code == "refused"
    assert app.runs.recent(50) == []


def test_a_new_target_gets_a_careful_guess() -> None:
    assert catalog.guess("backfill-all", "").safety == "refused"
    assert catalog.guess("pipeline-crawl", "Crawl now from the live regulator sites").safety == (
        "refused"
    )
    assert catalog.guess("api-logs", "Show the logs").safety == "refused"
    assert catalog.guess("watch-ui", "Rebuild with reload").safety == "refused"
    assert catalog.guess("purge", "Delete every cached row").safety == "destructive"
    assert catalog.guess("cache-down", "Stop the cache").safety == "stops-things"
    assert catalog.guess("schema-check", "Compare the schemas").safety == "safe"
    assert catalog.guess("docs-gen", "Regenerate the docs").safety == "changes-data"
    assert catalog.guess("frobnicate", "").safety == "changes-data"
    needs = catalog.guess("replay", 'Send one back: make replay ARGS="send --topic <dlq>"')
    assert needs.safety == "refused"
    assert needs.refused == catalog.NEEDS_ARGUMENTS
    optional = catalog.guess("sweep", 'Extract it: make sweep [ARGS="--dry-run"]')
    assert optional.safety == "changes-data"


def test_optional_choices_and_booleans_are_checked(app: server.App) -> None:
    migrate = app.catalog.specs["migrate"]
    assert catalog.normalise(app, migrate, {"service": ""}) == {"service": None}
    with pytest.raises(catalog.ParamError):
        catalog.normalise(app, migrate, {"service": "nobody"})
    with pytest.raises(catalog.ParamError):
        catalog.normalise(app, migrate, {"ARGS": "--destructive"})
    reset = app.catalog.specs["reset"]
    assert catalog.normalise(app, reset, {}) == {"backup_first": True}
    with pytest.raises(catalog.ParamError):
        catalog.normalise(app, reset, {"backup_first": "no"})


def test_the_web_check_is_safe_and_runs_on_a_test_copy_of_its_own(app: server.App) -> None:
    spec = app.catalog.specs["gate:web-e2e"]
    assert spec.title == "Click through the web app"
    assert spec.safety == "safe"
    assert not spec.needs_confirm
    assert spec.needs == ()  # memory stores: no Docker
    assert spec.duration == "10 to 15 minutes"
    words = " ".join(spec.what_happens)
    assert "separate, temporary copy of the ten services with throwaway data" in words
    assert "Stops the copy at the end: after the tests pass or fail, and when you cancel" in words
    assert "Your own data and running app are never touched" in words
    assert "the web app you have open keeps running while it builds" in words
    assert "ports 9401 to 9410 and 3410" in words
    assert "when it is not, the check uses your installed Google Chrome" in words
    assert "offers Download the test browser (about 150 MB), which asks first" in words
    built = catalog.build(app, spec, {})
    assert built.plan is not None
    assert [step.label for step in built.plan.steps] == [
        step.label for step in app.plans.web_check().steps
    ]
    entry = app.entry(spec)
    assert entry["enabled"] is True
    assert entry["safety"] == "safe"
    assert entry["steps"][0] == "check that the test copy can start"
    assert entry["steps"][-1] == "stop the test copy"
    variables = "STORE=memory WEB_STACK_DIR=var/web-stack-check SERVICE_PORT_BASE=9400"
    assert entry["command"].splitlines() == [
        f"make web-stack-down {variables}",
        f"make web-stack {variables}",
        f"make web-stack-wait {variables} WEB_STACK_WAIT_SECONDS=180",
        f"make web-seed {variables}",
        f"make web-e2e {variables} WEB_PORT=3410",
        f"make web-stack-down {variables}",
    ]


def test_the_browser_tests_on_their_own_are_never_run_here(app: server.App) -> None:
    spec = app.catalog.specs["make:web-e2e"]
    assert spec.safety == "refused"
    assert spec.refused == catalog.WEB_E2E_ALONE
    assert "ports 8001 to 8010" in spec.refused
    assert spec.covered_by == "gate:web-e2e"
    entry = app.entry(spec)
    assert (entry["enabled"], entry["reason"], entry["fix_action"]) == (
        False,
        catalog.WEB_E2E_ALONE,
        "gate:web-e2e",
    )
    for call in (app.preview, app.run):
        with pytest.raises(server.ApiError) as caught:
            call("make:web-e2e", {"params": {}})
        assert caught.value.code == "refused"


def test_the_test_browser_download_always_asks_first(app: server.App) -> None:
    # the web check offers it when there is no browser for its tests: it fetches about 150 MB
    spec = app.catalog.specs["make:web-e2e-install"]
    assert spec.needs_confirm
    assert spec.confirm == "Downloads about 150 MB from the internet."
    with pytest.raises(server.ApiError) as caught:
        app.run("make:web-e2e-install", {"params": {}})
    assert caught.value.status == 428


def test_make_check_is_refused_once_it_runs_the_browser_tests(project: core.Project) -> None:
    assert catalog.Catalog.load(project).specs["gate:check"].safety == "changes-data"
    with_e2e = dataclasses.replace(project, checks=[*project.checks, "web-e2e"])
    specs = catalog.Catalog.load(with_e2e).specs
    for action_id in ("gate:check", "make:check"):
        assert specs[action_id].safety == "refused"
        assert specs[action_id].refused == catalog.CHECK_RUNS_WEB_E2E
    assert specs["gates-in-order"].safety == "changes-data"  # it never runs web-e2e
