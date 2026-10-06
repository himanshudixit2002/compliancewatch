"""The action catalog over the checkout's own Makefile: every documented target is in it, each
with plain words and a safety class; whatever the runner would refuse is refused here first,
and nothing refused can be previewed or run."""

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
