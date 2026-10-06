"""Every button's plan: no shell, no forbidden target, a confirm wherever data goes, every make
target one of the checkout's, and every program a step may run declared where the checks see it."""

from pathlib import Path

import panel_core as core
import pytest

CHECKS = [
    "lint",
    "typecheck",
    "test",
    "importlint",
    "lock-check",
    "contracts-check",
    "runbooks-check",
    "migrations-check",
    "openapi-check",
    "ci-gate-check",
    "flags-check",
    "web-screens-check",
    "openapi-ts-check",
]
VOLUMES = [
    ("compliancewatch_postgres_data", "postgres_data"),
    ("compliancewatch_redis_data", "redis_data"),
    ("compliancewatch_redpanda_data", "redpanda_data"),
    ("compliancewatch_prometheus_data", "prometheus_data"),
    ("compliancewatch_tempo_data", "tempo_data"),
    ("compliancewatch_grafana_data", "grafana_data"),
]


def project(repo: Path, targets: dict[str, str] | None = None) -> core.Project:
    return core.Project(
        repo=repo,
        env=core.program_env({"PATH": "/usr/bin:/bin", "HOME": "/Users/dev"}),
        ports=core.resolve_ports({}, {}),
        make_targets=targets or {},
        checks=list(CHECKS),
        check_steps=[*core.CHECK_STEPS_FALLBACK, "extraction"],
        screens=list(core.SCREENS_FALLBACK),
        workers=["rulebook", "applicability-engine", "obligation", "notification", "pipeline"],
        relays=list(core.SERVICES),
        volumes=list(VOLUMES),
    )


def plans_for(proj: core.Project) -> core.Plans:
    registry = core.Registry(proj.repo / "var" / "control-panel")
    return core.Plans(proj, core.BackgroundManager(proj.repo, proj.env, registry))


@pytest.fixture
def plans(tmp_path: Path) -> core.Plans:
    return plans_for(project(tmp_path))


def test_no_plan_breaks_a_rule(plans: core.Plans) -> None:
    for plan in plans.all_plans():
        assert core.plan_problems(plan) == [], plan.title


def test_no_plan_runs_a_shell_or_reaches_the_regulator_sites(plans: core.Plans) -> None:
    for plan in plans.all_plans():
        for step in plan.steps:
            env = dict(step.env)
            assert env.get("CW_PIPELINE_CRAWL_ENABLED", "false") == "false", plan.title
            for argv in core.step_commands(step):
                assert all(isinstance(part, str) for part in argv), plan.title
                assert "-c" not in argv, plan.title
                assert not any("--destructive" in part for part in argv), plan.title
                assert Path(argv[0]).name not in {"sh", "bash", "zsh"}, plan.title
                if argv[0] == "make":
                    assert not {"backfill", "label"} & set(argv[1:]), plan.title


def test_every_make_target_is_one_of_the_makefile_s(plans: core.Plans) -> None:
    makefile = core.repo_root() / "Makefile"
    if not makefile.is_file():
        pytest.skip("no Makefile beside this copy of the panel")
    text = makefile.read_text(encoding="utf-8")
    known = core.parse_make_targets(text)
    for plan in plans.all_plans():
        assert core.plan_problems(plan, known) == [], plan.title
    sequence = [gate.target for gate in core.ci_sequence(core.parse_checks(text), known)]
    assert set(sequence) <= set(known)
    assert sequence[:3] == ["lint", "typecheck", "test"]


def pipeline_worker(env: tuple[tuple[str, str], ...] = ()) -> core.Cmd:
    return core.Cmd("pipeline worker", ("make", "worker", "SERVICE=pipeline"), env)


@pytest.mark.parametrize(
    ("step", "problem"),
    [
        (core.make("backfill", "SERVICE=pipeline"), "make backfill is never run here"),
        (core.make("label", "ARGS=index --source cbic"), "make label is never run here"),
        (core.make("product-check", "ARGS=--destructive"), "passes --destructive"),
        (core.make("product-seed", "ARGS=--rule gstr9_annual"), "product-seed runs with no"),
        (pipeline_worker((("CW_PIPELINE_CRAWL_ENABLED", "true"),)), "does not keep the crawl off"),
        (pipeline_worker(), "the pipeline worker runs only with the crawl off"),
        (core.Cmd("shell", ("/bin/bash", "-c", "make dev")), "runs bash"),
        (core.Cmd("shell", ("zsh", "-c", "make dev")), "runs zsh"),
        (core.Cmd("backfill", ("uv", "run", "pipeline-backfill")), "runs pipeline-backfill"),
        (core.make("migrate", "SERVICE=identity;rm -rf ~"), "unsafe make variable"),
        (core.make("dev-restore", "FILE=$(whoami).dump"), "unsafe make variable"),
        (core.make("dev-reset"), "a destructive target without a confirm"),
        (core.make("-e", "product-check"), "make runs without options here: -e"),
        (core.make("product-check", env=(("ARGS", "--destructive"),)), "passes --destructive"),
        (core.make("product-check", env=(("ARGS", "--json"),)), "carries ARGS"),
        (core.make("dev", env=(("MAKEFLAGS", "-- ARGS=x"),)), "carries MAKEFLAGS"),
        (core.Cmd("nothing", ()), "no program"),
        (core.Call("stop", lambda ctx: True, (("bash", "-c", "kill 1"),)), "runs bash"),
        (core.Call("down", lambda ctx: True, (("make", "dev-reset"),)), "without a confirm"),
    ],
)
def test_a_plan_that_breaks_a_rule_is_refused(step: core.Step, problem: str) -> None:
    problems = core.plan_problems(core.Plan("x", (step,)))
    assert any(problem in found for found in problems), problems


def test_an_empty_plan_or_an_unknown_target_is_refused() -> None:
    assert core.plan_problems(core.Plan("x", ())) == ["x: nothing to run"]
    plan = core.Plan("x", (core.make("dev"), core.make("no-such-target")))
    assert core.plan_problems(plan, {"dev"}) == [
        "make no-such-target: make no-such-target is not a target of this checkout's Makefile"
    ]


def test_the_complete_environment_must_keep_the_crawl_off() -> None:
    env = core.program_env({"PATH": "/usr/bin"})
    assert core.command_problems(("make", "dev"), env, complete_env=True) == []
    del env["CW_PIPELINE_CRAWL_ENABLED"]
    assert core.command_problems(("make", "dev"), env, complete_env=True) == [
        "does not keep the crawl off (CW_PIPELINE_CRAWL_ENABLED=false)"
    ]


def test_call_steps_declare_every_program_they_run(plans: core.Plans) -> None:
    down = next(s for s in plans.stop_everything().steps if s.label == "stop databases and Docker")
    assert isinstance(down, core.Call)
    assert down.commands == (("docker", "info"), ("make", "dev-down"), ("colima", "stop"))
    up = plans.docker_up()
    assert up.commands == (("docker", "info"), core.COLIMA_START)
    web = plans.stop_web_call()
    assert web.commands == core.scan_commands()
    assert core.PS_ARGV in plans.start_web_call().commands
    # A Call that runs make dev-reset is checked like a Cmd: it needs the plan's confirm
    down_reset = core.Call("x", lambda ctx: True, (("make", "dev-reset"),))
    confirmed = core.Plan("x", (down_reset,), confirm="Reset?")
    assert core.plan_problems(confirmed) == []


def test_the_product_runs_beside_the_ui_only_web_app(plans: core.Plans) -> None:
    start = plans.product_start().steps
    assert isinstance(start[1], core.Cmd)
    assert start[1].argv == ("make", "product", "WEB_PORT=3400")
    wait = plans.product_wait().steps[0]
    assert isinstance(wait, core.Cmd)
    assert wait.argv == ("make", "product-wait", "WEB_PORT=3400")
    # make product-e2e's next start would collide with the product's web app on 3400
    e2e = plans.product_e2e().steps[0]
    assert isinstance(e2e, core.Cmd)
    assert e2e.argv == ("make", "product-e2e", "PRODUCT_E2E_PORT=3401")


def test_the_check_runs_all_steps_or_one_and_never_rollback(plans: core.Plans) -> None:
    assert core.step_commands(plans.product_check().steps[0]) == (("make", "product-check"),)
    one = core.step_commands(plans.product_check("extraction").steps[0])
    assert one == (("make", "product-check", "ARGS=--step extraction"),)
    assert core.plan_problems(plans.product_check("rollback")) == [
        "product-check --step rollback: nothing to run"
    ]
    assert core.plan_problems(plans.product_check("loop; make backfill")) != []


def test_the_product_seed_asks_the_product_before_it_runs(plans: core.Plans) -> None:
    first, second = plans.product_seed().steps
    assert isinstance(first, core.Call)
    assert first.label == "check the product answers"
    assert first.commands == ()
    assert core.step_commands(second) == (("make", "product-seed"),)


def test_logs_are_bounded_and_never_follow(plans: core.Plans) -> None:
    (logs,) = core.step_commands(plans.container_logs("redpanda").steps[0])
    assert logs[-5:] == ("logs", "--no-color", "--tail", "200", "redpanda")
    assert "--follow" not in logs
    assert logs[:3] == ("docker", "compose", "--profile")
    assert core.step_commands(plans.product_logs("worker").steps[0]) == (
        ("make", "product-logs", "PROC=worker", "FOLLOW=0"),
    )
    (image,) = core.step_commands(plans.product_image_logs("release").steps[0])
    assert image[-1] == "FOLLOW=0"
    path = plans.project.repo / "var" / "web-stack" / "identity.log"
    tail = core.step_commands(plans.tail("identity log", path).steps[0])
    assert tail == (("tail", "-n", "200", "var/web-stack/identity.log"),)


def test_workers_and_relays_start_with_the_crawl_off(plans: core.Plans) -> None:
    for plan in (plans.worker_start("pipeline"), plans.relay_start("pipeline")):
        (step,) = plan.steps
        assert isinstance(step, core.Call)
        assert dict(step.env) == {"CW_PIPELINE_CRAWL_ENABLED": "false"}
    worker = plans.worker_start("pipeline").steps[0]
    assert isinstance(worker, core.Call)
    assert worker.commands == (("make", "worker", "SERVICE=pipeline"), core.PS_ARGV)
    relay = plans.relay_start("rulebook").steps[0]
    assert isinstance(relay, core.Call)
    assert relay.commands[0] == ("make", "relay", "SERVICE=rulebook")


def test_background_files_live_under_var_control_panel(tmp_path: Path) -> None:
    spec = core.worker_spec(tmp_path, "pipeline")
    assert spec.pid_file == tmp_path / "var" / "control-panel" / "worker-pipeline.pid"
    assert spec.log_file == tmp_path / "var" / "control-panel" / "worker-pipeline.log"
    assert spec.marker == "worker SERVICE=pipeline"
    relay = core.relay_spec(tmp_path, "identity")
    assert relay.pid_file.name == "relay-identity.pid"
    # The web app keeps the files the panel always wrote, so make web-stack-down stops it too
    web = core.web_spec(tmp_path, 3000)
    assert web.pid_file == tmp_path / "var" / "web-stack" / "web.pid"
    assert web.argv == ("pnpm", "--filter", "web", "dev")
    assert dict(web.env) == {"PORT": "3000"}


def test_restore_reads_the_dump_first_and_says_what_it_drops(plans: core.Plans) -> None:
    plan = plans.restore("var/backups/20261006T101500Z.dump")
    check, restore = plan.steps
    assert isinstance(check, core.Call)
    assert check.commands == (core.PG_RESTORE_LIST,)
    assert core.PG_RESTORE_LIST == (
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "pg_restore",
        "--list",
    )
    assert core.step_commands(restore) == (
        ("make", "dev-restore", "FILE=var/backups/20261006T101500Z.dump"),
    )
    assert plan.confirm is not None
    assert "drops the database compliancewatch" in plan.confirm
    assert "Everything written since the dump was taken is lost" in plan.confirm
    for odd in ("var/backups/x;y.dump", "/etc/x.dump", "var/backups/../x.dump"):
        assert core.plan_problems(plans.restore(odd)) == [f"restore {odd}: nothing to run"]


def test_reset_names_every_volume_and_can_back_up_first(plans: core.Plans) -> None:
    with_backup = [step.label for step in plans.reset(backup_first=True).steps]
    assert with_backup == [
        "back up the database first",
        "stop the UI-only stack",
        "stop the product's processes",
        "stop the panel's workers and relays",
        "make dev-reset",
        "make dev",
        "make migrate",
        "seed rulebook",
    ]
    without = [step.label for step in plans.reset(backup_first=False).steps]
    assert without == with_backup[1:]
    confirm = plans.reset(backup_first=False).confirm or ""
    for full, _ in VOLUMES:
        assert f"\n  {full}" in confirm
    assert "compliancewatch_postgres_data: Postgres: every service's schema" in confirm
    assert "anonymous volumes" in confirm


def test_the_ci_gates_run_in_ci_s_order_and_keep_going(plans: core.Plans) -> None:
    plan = plans.gates_in_order()
    assert plan.keep_going
    assert plan.gates
    steps = {cmd[1]: cmd for step in plan.steps for cmd in core.step_commands(step)}
    targets = list(steps)
    assert targets[:3] == ["lint", "typecheck", "test"]
    assert "check" not in targets
    assert "web-e2e" not in targets
    assert set(CHECKS) <= set(targets)
    assert targets.index("py-test-integration") > targets.index("migrations-check")
    assert targets[-2:] == ["sast", "deps-scan"]
    integration = next(s for s in plan.steps if s.label == "py-test-integration")
    assert dict(integration.env) == {
        "TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE": "/var/run/docker.sock"
    }
    assert steps["eval"] == ("make", "eval", "EVAL_PROFILE=ci")


def test_the_ci_gates_leave_out_a_target_the_makefile_no_longer_has(tmp_path: Path) -> None:
    targets = {name: "" for name in [*core.CI_ORDER, *CHECKS] if name != "ci-lint"}
    proj = project(tmp_path, targets)
    plan = plans_for(proj).gates_in_order()
    names = [cmd[1] for step in plan.steps for cmd in core.step_commands(step)]
    assert "ci-lint" not in names
    assert core.plan_problems(plan, proj.known_targets) == []
    sequence = [gate.target for gate in core.ci_sequence(["lint", "new-gate"], None)]
    assert sequence.index("new-gate") == sequence.index("openapi-ts-check") + 1
    assert sequence.count("lint") == 1


def test_each_gate_has_one_button() -> None:
    labels = [gate.label for gate in core.GATES]
    assert len(labels) == len(set(labels))
    assert {gate.target for gate in core.GATES} == {
        "check",
        "lint",
        "typecheck",
        "test",
        "py-test-integration",
        "eval",
        "eval-check",
        "openapi-compat",
        "contracts-check",
        "alerts-check",
        "flags-check",
        "migrations-check",
        "sast",
        "deps-scan",
        "web-screens-check",
        "web-e2e",
        "ci-lint",
    }


def test_the_big_buttons_keep_their_order_and_ask_before_stopping(plans: core.Plans) -> None:
    start = plans.start_everything()
    assert [step.label for step in start.steps] == [
        "start Docker",
        "start databases and queues",
        "migrate databases",
        "start services",
        "wait for services",
        "start web app",
        "open http://localhost:3000",
    ]
    assert core.step_commands(start.steps[-1]) == (("open", "http://localhost:3000"),)
    assert plans.stop_everything().confirm
    assert plans.docker_stop().confirm
    assert core.step_commands(plans.docker_stop().steps[0]) == (("colima", "stop"),)
    colima = "colima start --cpu 4 --memory 8 --disk 60 --dns 1.1.1.1 --dns 8.8.8.8"
    assert colima == " ".join(core.COLIMA_START)


def test_the_project_reads_the_checkout_and_writes_nothing(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("dev: check-docker ## Start the stack\nCHECKS := lint\n")
    worker = tmp_path / "services" / "pipeline" / "src" / "pipeline"
    worker.mkdir(parents=True)
    (worker / "worker.py").write_text('"""The pipeline worker."""\n')
    versions = tmp_path / "services" / "identity" / "migrations" / "versions"
    versions.mkdir(parents=True)
    (versions / "0003_outbox.py").write_text('op.create_table("outbox_event")\n')
    (tmp_path / ".env").write_text("WEB_PORT=3200\nCOMPOSE_PROJECT_NAME=cw2\n")
    (tmp_path / "docker-compose.yml").write_text(
        "name: compliancewatch\nservices:\n  postgres:\n    volumes:\n      - pg:/x\n"
        "volumes:\n  postgres_data:\n  redis_data:\n"
    )
    proj = core.Project.load(tmp_path, {"PATH": "/usr/bin"})
    assert proj.make_targets == {"dev": "Start the stack"}
    assert proj.known_targets == {"dev": "Start the stack"}
    assert proj.checks == ["lint"]
    assert proj.workers == ["pipeline"]
    assert proj.relays == ["identity"]
    assert proj.ports["WEB_PORT"] == 3200
    assert proj.volumes == [
        ("cw2_postgres_data", "postgres_data"),
        ("cw2_redis_data", "redis_data"),
    ]
    assert proj.check_steps == list(core.CHECK_STEPS_FALLBACK)
    assert proj.screens == list(core.SCREENS_FALLBACK)
    assert [spec.key for spec in proj.backgrounds()] == ["web", "worker-pipeline", "relay-identity"]
    assert proj.env["CW_PIPELINE_CRAWL_ENABLED"] == "false"
    assert not (tmp_path / "var").exists()
    missing = core.Project.load(tmp_path / "nowhere", {"PATH": "/usr/bin"})
    assert missing.make_targets == {}
    assert missing.known_targets is None
    assert missing.notes == [f"no Makefile in {tmp_path / 'nowhere'}: every make step will fail"]
    assert [name for _, name in missing.volumes] == list(core.VOLUMES_FALLBACK)
