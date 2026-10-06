"""The actions of M2-7's make targets, and the one allowlist of what an action may pass make as
ARGS: counting the extraction backlog passes exactly ``--dry-run``, and nothing else passes
anything a person typed."""

from dataclasses import replace
from pathlib import Path

import panel_catalog as catalog
import panel_core as core
import panel_demo as demo
import panel_server as server
import pytest


@pytest.fixture
def app() -> server.App:
    """The helper's logic over the demo checkout, whose Makefile has M2-7's targets."""
    return server.App(demo.DemoBackend(), token="x" * 43, port=1, prefs=server.Prefs(None))


def plan(*argv: str) -> core.Plan:
    return core.Plan("x", (core.Cmd("x", argv),))


def test_counting_the_backlog_passes_exactly_dry_run(app: server.App) -> None:
    assert catalog.args_allowed(app, "extract-backlog-count", "--dry-run")
    for value in (
        "",
        "--json",
        "--dry-run --json",
        "--dry-run ",
        " --dry-run",
        "--DRY-RUN",
        "--dry-run --limit 1000",
        "--source cbic_notifications",
        "--dry-run;--json",
    ):
        assert not catalog.args_allowed(app, "extract-backlog-count", value), value


def test_no_other_action_may_pass_it(app: server.App) -> None:
    others = [spec_id for spec_id in app.catalog.specs if spec_id != "extract-backlog-count"]
    assert "extract-backlog" in others
    assert "make:extract-backlog" in others
    for spec_id in [*others, "no-such-action", ""]:
        assert not catalog.args_allowed(app, spec_id, "--dry-run"), spec_id


def test_a_plan_that_passes_arguments_its_action_may_not_is_refused(app: server.App) -> None:
    specs = app.catalog.specs
    count, extract = specs["extract-backlog-count"], specs["extract-backlog"]
    catalog.check_arguments(app, count, plan("make", "extract-backlog", "ARGS=--dry-run"))
    for spec, argv in (
        (extract, ("make", "extract-backlog", "ARGS=--dry-run")),
        (specs["make:extract-backlog"], ("make", "extract-backlog", "ARGS=--dry-run")),
        (count, ("make", "extract-backlog", "ARGS=--dry-run --json")),
        (count, ("make", "extract-backlog", "ARGS=--limit 1000")),
        (specs["backup"], ("make", "dev-backup", "ARGS=--dry-run")),
    ):
        with pytest.raises(catalog.ParamError):
            catalog.check_arguments(app, spec, plan(*argv))
    # a Call's declared programs count too
    call = core.Plan(
        "x",
        (core.Call("x", lambda ctx: True, (("make", "extract-backlog", "ARGS=--dry-run"),)),),
    )
    with pytest.raises(catalog.ParamError):
        catalog.check_arguments(app, extract, call)


def test_the_curated_arguments_still_build(app: server.App) -> None:
    specs = app.catalog.specs
    count = catalog.build(app, specs["extract-backlog-count"], {}).plan
    assert count is not None
    assert [step.argv for step in count.steps if isinstance(step, core.Cmd)] == [
        ("make", "extract-backlog", "ARGS=--dry-run")
    ]
    extract = catalog.build(app, specs["extract-backlog"], {}).plan
    assert extract is not None
    assert [step.argv for step in extract.steps if isinstance(step, core.Cmd)] == [
        ("make", "extract-backlog")
    ]
    assert catalog.build(app, specs["seed-check"], {}).plan is not None
    step = core.selectable_steps(app.project.check_steps)[0]
    assert catalog.args_allowed(app, "product-check", f"--step {step}")
    assert not catalog.args_allowed(app, "product-check", "--step rollback")
    assert catalog.build(app, specs["product-check"], {"step": step}).plan is not None


def test_the_backlog_actions_come_with_their_target(app: server.App, tmp_path: Path) -> None:
    specs = app.catalog.specs
    assert specs["extract-backlog-count"].safety == "safe"
    assert specs["extract-backlog-count"].kind == "read"
    extract = specs["extract-backlog"]
    assert extract.safety == "changes-data"
    assert extract.calls_model
    assert "At most 1,000 documents in one run; run it again for the rest." in (
        extract.what_happens
    )
    assert specs["make:extract-backlog"].covered_by == "extract-backlog"
    assert specs["make:replay"].safety == "refused"
    assert specs["make:replay"].refused == (
        "Needs a topic and an event id: run it from a terminal, see docs/runbooks/outbox-relay.md."
    )
    assert specs["make:golden-export"].safety == "refused"
    assert specs["make:golden-export"].refused == (
        "Needs a date and an output folder: run it from a terminal, see the rulebook README."
    )
    (tmp_path / "Makefile").write_text("dev: ## Start the stack\n")
    without = catalog.Catalog.load(core.Project.load(tmp_path, {"PATH": "/usr/bin"}))
    assert "extract-backlog" not in without.specs
    assert "extract-backlog-count" not in without.specs


def test_the_confirm_names_the_product_s_model_provider() -> None:
    with_product = server.App(demo.DemoBackend(), token="x" * 43, port=1, prefs=server.Prefs(None))
    backend = with_product.backend
    assert isinstance(backend, demo.DemoBackend)
    backend.world.product = {"internal", "public", "worker", "web"}
    with_product.on_probe("status", backend.probe_status())
    product = with_product.status_body()["product"]
    assert product["llm_provider"] == "fake"
    preview = with_product.preview("extract-backlog", {"params": {}})
    warning = next(w for w in preview["confirm"]["warnings"] if w["code"] == "provider")
    assert warning["tone"] == "info"
    assert "CW_LLM_PROVIDER=fake" in warning["message"]
    backend.world.product = set()
    with_product.on_probe("status", backend.probe_status())
    assert with_product.status_body()["product"]["llm_provider"] is None
    preview = with_product.preview("extract-backlog", {"params": {}})
    unknown = next(w for w in preview["confirm"]["warnings"] if w["code"] == "provider")
    assert unknown["tone"] == "warning"
    assert unknown["title"] == "This may call a paid model"
    assert preview["confirm_token"]


def test_a_paid_provider_is_named_and_a_model_call_always_asks() -> None:
    app = server.App(demo.DemoBackend(), token="x" * 43, port=1, prefs=server.Prefs(None))
    backend = app.backend
    assert isinstance(backend, demo.DemoBackend)
    status = backend.probe_status()
    app.on_probe("status", replace(status, llm_provider="vercel"))
    preview = app.preview("extract-backlog", {"params": {}})
    paid = next(w for w in preview["confirm"]["warnings"] if w["code"] == "provider")
    assert paid["tone"] == "warning"
    assert "vercel" in paid["title"]
    # a model call asks first even if its class were safe
    spec = replace(app.catalog.specs["extract-backlog"], safety="safe")
    assert spec.needs_confirm


def test_the_gateway_s_provider_comes_from_the_product_s_log(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    assert core.gateway_provider(log) is None
    log.write_text(
        '{"provider": "fake", "event": "gateway_wired", "service": "llm-gateway"}\n'
        '{"event": "started"}\n'
        '{"provider": "vercel", "event": "gateway_wired", "service": "llm-gateway"}\n'
        "not json at all\n"
    )
    assert core.gateway_provider(log) == "vercel"
    log.write_text('{"provider": "<script>", "event": "gateway_wired"}\n')
    assert core.gateway_provider(log) is None
    log.write_text('{"event": "gateway_wired" broken\n')
    assert core.gateway_provider(log) is None


def test_a_refusal_because_the_switch_is_off_says_what_to_do() -> None:
    error = server.classify_failure(
        [
            "pipeline-extract-backlog: refused: CW_PIPELINE_EXTRACTION_ENABLED is off (flag "
            "pipeline.extraction); turn it on for the worker and here, or count with --dry-run",
            "make: *** [extract-backlog] Error 2",
        ],
        timed_out=False,
    )
    assert error["code"] == "extraction-off"
    assert error["action"] == "extract-backlog-count"
