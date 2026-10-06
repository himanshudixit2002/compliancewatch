"""The parsers behind the panel's probes, fed with output recorded from the real programs."""

import json
import os
from pathlib import Path

import panel_core as core
import pytest

ENV_FILE = """\
# Postgres
POSTGRES_PORT=25432
export WEB_PORT="3200"
SERVICE_PORT_BASE=9200  # a second clone
CW_MVP_INTERNAL_PORT='8180'
PRODUCT_WORKER_PORT=9999
LANGFUSE_PORT=not-a-port
not a line
1BAD=x
CW_EMPTY=
"""


def test_env_files_read_as_the_recipes_source_them() -> None:
    values = core.parse_env_file(ENV_FILE)
    assert values == {
        "POSTGRES_PORT": "25432",
        "WEB_PORT": "3200",
        "SERVICE_PORT_BASE": "9200",
        "CW_MVP_INTERNAL_PORT": "8180",
        "PRODUCT_WORKER_PORT": "9999",
        "LANGFUSE_PORT": "not-a-port",
        "CW_EMPTY": "",
    }


def test_ports_come_from_the_environment_then_env_then_the_defaults() -> None:
    ports = core.resolve_ports(core.parse_env_file(ENV_FILE), {"WEB_PORT": "3300"})
    assert ports["WEB_PORT"] == 3300
    assert ports["POSTGRES_PORT"] == 25432
    assert ports["CW_MVP_INTERNAL_PORT"] == 8180
    assert ports["LANGFUSE_PORT"] == 3010
    assert ports["TEMPORAL_UI_PORT"] == 8233
    # A make variable: .env never sets it, the environment does
    assert ports["PRODUCT_WORKER_PORT"] == 8081
    assert core.resolve_ports({}, {"PRODUCT_WORKER_PORT": "8091"})["PRODUCT_WORKER_PORT"] == 8091
    assert [ports.service(name) for name in ("identity", "pipeline")] == [9201, 9210]


def test_the_port_catalogue_holds_both_stacks_and_the_stack_s_tools() -> None:
    ports = core.resolve_ports({}, {})
    catalogue = core.port_catalogue(ports)
    numbers = [entry.port for entry in catalogue]
    assert numbers == sorted(numbers)
    assert set(range(8001, 8011)) <= set(numbers)
    assert {3000, 3400, 8000, 8080, 8081, 5432, 6379, 19092, 7233, 8233, 3030, 9090} <= set(numbers)
    links = core.stack_links(ports)
    assert [label for label, _, _ in links][:5] == [
        "Temporal UI",
        "Grafana",
        "Prometheus",
        "Langfuse",
        "Unleash",
    ]
    # Every link is a port the compose stack publishes
    published = {ports[key] for key in core.PORT_DEFAULTS if not key.startswith(("CW_", "WEB"))}
    for _, url, container in links:
        assert int(url.split(":")[2].split("/")[0]) in published
        assert container in {service.name for service in core.COMPOSE_SERVICES}


MAKEFILE = """\
.PHONY: help
help: ## Show this help
\t@grep -hE '^[a-zA-Z0-9_-]+:[^#]*## ' $(MAKEFILE_LIST)
SERVICE ?=
PKG_profile := profile_service
check-docker: check-docker-cli
\t@docker info >/dev/null 2>&1
dev: check-docker ## Start Postgres, Redis, Redpanda, Temporal (+UI); waits for health
CHECKS := lint typecheck test importlint lock-check contracts-check runbooks-check
.SECONDEXPANSION:
check: $$(CHECKS) ## Everything CI runs before integration tests (the gates listed in CHECKS)
CHECKS += migrations-check
migrations-check: check-uv ## Migration files: one head per service
CHECKS += openapi-check
CHECKS += ci-gate-check
CHECKS += flags-check
CHECKS += web-screens-check openapi-ts-check  # the web gates
x:=y
"""


def test_make_targets_and_their_help_come_from_the_makefile() -> None:
    targets = core.parse_make_targets(MAKEFILE)
    assert list(targets) == ["help", "check-docker", "dev", "check", "migrations-check"]
    assert targets["help"] == "Show this help"
    assert targets["check-docker"] == ""
    assert targets["dev"].startswith("Start Postgres")


def test_make_check_s_gates_are_checks_with_every_addition() -> None:
    assert core.parse_checks(MAKEFILE) == [
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


CHECK_PY = '''\
STEPS: list[Step] = [
    Step("health", "both listeners and every worker loop are up", health),
    Step("honesty", "only cited seed rules are published, all still needs_review", honesty),
    Step(
        "rollback",
        "a withdrawn rule closes its obligations in both tenants and sends withdrawal notices",
        rollback,
    ),
    Step("review", "every seed draft waits in the review queue", review),
]
"""The steps in the order they run. A later package appends its own Step."""
STEPS.append(Step("extraction", "the pipeline extracts", extraction))
'''


def test_the_check_s_steps_are_read_in_order_and_rollback_is_never_offered() -> None:
    steps = core.parse_check_steps(CHECK_PY)
    assert steps == ["health", "honesty", "rollback", "review", "extraction"]
    assert core.selectable_steps(steps) == ["health", "honesty", "review", "extraction"]
    assert "rollback" not in core.selectable_steps(core.CHECK_STEPS_FALLBACK)


def compose_line(service: str, state: str, health: str, status: str, **extra: object) -> str:
    row = {
        "Command": '"docker-entrypoint.s…"',
        "ExitCode": extra.get("exit_code", 0),
        "Health": health,
        "Name": f"compliancewatch-{service}-1",
        "Project": "compliancewatch",
        "Publishers": extra.get("publishers", []),
        "Service": service,
        "State": state,
        "Status": status,
    }
    return json.dumps(row)


POSTGRES = [
    {"URL": "0.0.0.0", "TargetPort": 5432, "PublishedPort": 5432, "Protocol": "tcp"},
    {"URL": "::", "TargetPort": 5432, "PublishedPort": 5432, "Protocol": "tcp"},
]
REDPANDA = [
    {"URL": "", "TargetPort": 8081, "PublishedPort": 0, "Protocol": "tcp"},
    {"URL": "0.0.0.0", "TargetPort": 19092, "PublishedPort": 19092, "Protocol": "tcp"},
    {"URL": "0.0.0.0", "TargetPort": 9644, "PublishedPort": 19644, "Protocol": "tcp"},
]


def test_compose_ps_reads_each_container_from_json_lines() -> None:
    text = "\n".join(
        [
            compose_line(
                "postgres", "running", "healthy", "Up 18 hours (healthy)", publishers=POSTGRES
            ),
            compose_line(
                "redpanda", "running", "healthy", "Up 18 hours (healthy)", publishers=REDPANDA
            ),
            compose_line("temporal-ui", "running", "", "Up 18 hours"),
            compose_line("grafana", "running", "starting", "Up 4 seconds (health: starting)"),
            compose_line("mvp-release", "exited", "", "Exited (0) 2 minutes ago"),
            compose_line("mvp-app", "exited", "", "Exited (1) 1 minute ago", exit_code=1),
        ]
    )
    containers = core.parse_compose_ps(text)
    assert containers["postgres"] == core.Container(
        "postgres", "running", "healthy", "Up 18 hours (healthy)", 0, (5432,)
    )
    assert containers["redpanda"].ports == (19092, 19644)
    assert containers["temporal-ui"].up
    assert not containers["grafana"].up
    assert containers["mvp-app"].exit_code == 1
    status = core.Status(True, containers, {}, {}, {}, 0.0)
    assert status.infra_up == 3


def test_compose_ps_also_reads_the_array_older_compose_printed() -> None:
    text = "[" + compose_line("redis", "running", "healthy", "Up") + "]"
    assert list(core.parse_compose_ps(text)) == ["redis"]
    assert core.parse_compose_ps("") == {}
    assert core.parse_compose_ps("not json\n") == {}


RPK_GROUPS = """
[{"group_name": "applicability-engine.profiles", "coordinator_partition": "__consumer_offsets/2",
  "state": "Empty", "balancer": "", "members": 0, "coordinator_node": 0, "total_lag": 0,
  "partitions": [{"partition": 0, "current_offset": 316, "log_start_offset": 0,
                  "log_end_offset": 316, "lag": 0, "topic": "profile.updated", "member_id": "",
                  "client_id": "", "host": ""}],
  "members_details": []},
 {"group_name": "notification.obligations", "state": "Stable", "members": 1, "total_lag": 7,
  "partitions": [{"partition": 0, "lag": 5, "topic": "obligation.created"},
                 {"partition": 0, "lag": 2, "topic": "obligation.due_soon"},
                 {"partition": 0, "lag": 0, "topic": "obligation.closed"}]}]
"""

RPK_TOPICS = """
[{"summary": {"name": "__consumer_offsets", "internal": true, "partitions": 3, "replicas": 1},
  "configs": [], "partitions": [{"partition": 0, "log_start_offset": 0, "high_watermark": 9}]},
 {"summary": {"name": "profile.updated", "internal": false, "partitions": 1, "replicas": 1,
              "error": ""},
  "configs": [{"key": "cleanup.policy", "value": "delete", "source": "DYNAMIC_TOPIC_CONFIG"}],
  "partitions": [{"partition": 0, "leader": 0, "epoch": 2, "replicas": [0],
                  "log_start_offset": 0, "high_watermark": 316}]},
 {"summary": {"name": "obligation.created.notification.obligations.dlq", "partitions": 1},
  "partitions": [{"partition": 0, "log_start_offset": 1, "high_watermark": 3}]}]
"""


def test_consumer_groups_carry_their_lag_per_topic() -> None:
    groups = core.parse_rpk_groups(RPK_GROUPS)
    assert groups == [
        core.GroupLag("applicability-engine.profiles", "Empty", 0, 0, (("profile.updated", 0),)),
        core.GroupLag(
            "notification.obligations",
            "Stable",
            1,
            7,
            (("obligation.closed", 0), ("obligation.created", 5), ("obligation.due_soon", 2)),
        ),
    ]
    assert core.parse_rpk_groups("") == []
    with pytest.raises(ValueError, match="Expecting value"):
        core.parse_rpk_groups("no groups")


def test_topics_carry_their_message_counts_and_leave_internal_ones_out() -> None:
    topics = core.parse_rpk_topics(RPK_TOPICS)
    assert topics == [
        core.TopicInfo("obligation.created.notification.obligations.dlq", 1, 2),
        core.TopicInfo("profile.updated", 1, 316),
    ]
    assert topics[0].dead_letters
    assert not topics[1].dead_letters
    listed = '[{"name": "applicability.decided", "partitions": 1, "replicas": 1}]'
    assert core.parse_rpk_topics(listed) == [core.TopicInfo("applicability.decided", 1, None)]


def test_git_s_porcelain_and_counts() -> None:
    assert core.count_porcelain("## candidate-intake\n M Makefile\n?? output/\n") == 2
    assert core.count_porcelain("") == 0
    assert core.parse_ahead_behind("0\t27\n") == (27, 0)
    assert core.parse_ahead_behind("3 1") == (1, 3)
    assert core.parse_ahead_behind("fatal: bad revision") is None
    assert core.GitState(branch="main").on_main
    assert not core.GitState(branch="pipeline-extraction").on_main


@pytest.mark.parametrize(
    ("remote", "page"),
    [
        (
            "https://github.com/himanshudixit2002/compliancewatch.git",
            "https://github.com/himanshudixit2002/compliancewatch",
        ),
        ("git@github.com:owner/repo.git", "https://github.com/owner/repo"),
        ("ssh://git@github.com/owner/repo", "https://github.com/owner/repo"),
        ("https://user:not-a-token@github.com/owner/repo.git", "https://github.com/owner/repo"),
        ("https://gitlab.com/owner/repo.git", None),
        ("", None),
    ],
)
def test_the_github_page_of_a_remote_keeps_no_credentials(remote: str, page: str | None) -> None:
    assert core.github_url(remote) == page


def test_github_links_name_the_branch_when_it_is_not_main() -> None:
    base = "https://github.com/owner/repo"
    assert core.github_links(base, "main") == [
        ("Pull requests", f"{base}/pulls"),
        ("Actions", f"{base}/actions"),
        ("Repository", base),
        ("Branch main", f"{base}/tree/main"),
    ]
    links = dict(core.github_links(base, "feat/x y"))
    assert links["Compare with main"] == f"{base}/compare/main...feat/x%20y"
    assert "Branch HEAD" not in dict(core.github_links(base, "HEAD"))


REGISTRY = json.dumps(
    {
        "flags": [
            {
                "name": "applicability.fanout",
                "type": "bool",
                "default": False,
                "owner": "core-product",
                "description": "The engine's consumer of rule.published starts a fan-out.",
                "removal": "Once fan-outs have run in production for 30 days.",
                "expires": "2027-03-31",
                "env": "CW_APPLICABILITY_FANOUT_ENABLED",
            },
            {
                "name": "auth.mode",
                "type": "string",
                "default": "header",
                "values": ["header", "dual", "token"],
                "owner": "platform",
                "description": "How a Python service reads its caller.",
                "removal": "Delete header and dual once production runs token.",
                "expires": "2027-03-31",
                "env": "CW_AUTH_MODE",
            },
            {
                "name": "profile.gstin_category_prefill",
                "type": "bool",
                "default": False,
                "owner": "core-product",
                "description": "Pre-fill the category from the GSTIN lookup.",
                "removal": "Once the lookup provider is live.",
                "expires": "2027-03-31",
            },
            {
                "name": "web.qa_enabled",
                "type": "bool",
                "default": False,
                "owner": "ai-platform",
                "description": "The Ask tab.",
                "removal": "Once KAG is accepted.",
                "expires": "2027-03-31",
                "env": "CW_WEB_FLAG_QA_ENABLED",
            },
        ]
    }
)


def test_flags_show_their_variable_and_the_file_that_sets_it() -> None:
    files = [
        (".env", {"CW_AUTH_MODE": "dual", "CW_WEB_FLAG_QA_ENABLED": "false"}),
        ("apps/web/.env.local", {"CW_WEB_FLAG_QA_ENABLED": "true"}),
    ]
    rows = {row.name: row for row in core.flag_rows(REGISTRY, files)}
    assert list(rows) == [
        "applicability.fanout",
        "auth.mode",
        "profile.gstin_category_prefill",
        "web.qa_enabled",
    ]
    fanout = rows["applicability.fanout"]
    assert (fanout.default, fanout.env, fanout.value, fanout.source) == (
        "false",
        "CW_APPLICABILITY_FANOUT_ENABLED",
        None,
        "",
    )
    assert (rows["auth.mode"].value, rows["auth.mode"].source) == ("dual", ".env")
    # A flag with no variable of its own is set with CW_FLAG_<NAME> (py_common.flags)
    assert rows["profile.gstin_category_prefill"].env == "CW_FLAG_PROFILE_GSTIN_CATEGORY_PREFILL"
    # The first file that sets a variable wins
    assert (rows["web.qa_enabled"].value, rows["web.qa_enabled"].source) == ("false", ".env")
    assert rows["applicability.fanout"].expires == "2027-03-31"


SCREENS = """
export const SCREENS: readonly Screen[] = [
  {
    id: "admin.home",
    kind: "page",
    route: "/admin",
    title: "Internal tools",
    uses: [],
    awaits: [],
    status: "live",
  },
  {
    id: "admin.review",
    kind: "page",
    route: "/admin/review",
    title: "Review queue",
    awaits: [servicesTrack("WP22", "rulebook", "GET", "/v1/rulebook/review/tasks")],
    status: "ready",
  },
  {
    id: "admin.fan-outs",
    kind: "page",
    route: "/admin/fan-outs",
    title: "Fan-outs",
    nav: { group: "Rules", order: 4 },
    status: "live",
  },
  {
    id: "admin.fan-out",
    kind: "page",
    route: "/admin/fan-outs/[ruleVersionId]",
    title: "Fan-out control",
    status: "live",
  },
  {
    id: "admin.decisions",
    kind: "page",
    route: "/admin/decisions",
    title: "Decision review",
    status: "live",
  },
  { id: "owner.ask", kind: "page", route: "/b/[businessId]/ask", title: "Ask", status: "live" },
];
"""


def test_admin_pages_are_the_live_ones_without_a_parameter() -> None:
    screens = core.parse_screens(SCREENS)
    assert [(s.id, s.status) for s in screens] == [
        ("admin.home", "live"),
        ("admin.review", "ready"),
        ("admin.fan-outs", "live"),
        ("admin.fan-out", "live"),
        ("admin.decisions", "live"),
        ("owner.ask", "live"),
    ]
    pages, missing = core.admin_pages(screens, core.PRODUCT_ADMIN)
    assert [page.route for page in pages] == ["/admin/fan-outs", "/admin/decisions", "/admin"]
    assert [page.title for page in missing] == ["Review queue"]
    pages, _ = core.admin_pages(screens, core.PIPELINE_ADMIN, only=True)
    assert pages == []
    fallback, _ = core.admin_pages(core.SCREENS_FALLBACK, core.PRODUCT_ADMIN)
    assert fallback[0].route == "/admin/fan-outs"


@pytest.mark.parametrize(
    ("raw", "text"),
    [
        ("plain line\n", "plain line"),
        ("\x1b[32m✓ passed\x1b[0m\n", "✓ passed"),
        ("Downloading  10%\rDownloading  55%\rDownloading 100%\n", "Downloading 100%"),
        ("\r\n", ""),
    ],
)
def test_output_lines_lose_colour_codes_and_progress_frames(raw: str, text: str) -> None:
    assert core.clean_line(raw) == text


def test_error_lines_are_marked_but_a_count_of_none_is_not() -> None:
    assert core.line_tag("error: Docker daemon not reachable") == "err"
    assert core.line_tag("FAILED tests/unit/test_x.py::test_y") == "err"
    assert core.line_tag("1 failed, 20 passed in 3.1s") == "err"
    assert core.line_tag("20 passed, 0 failed") is None
    assert core.line_tag("Found 0 errors") is None
    assert core.line_tag("make: Nothing to be done") is None


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("00:28", 28), ("02:28:08", 8888), ("18-02:00:00", 18 * 86400 + 7200), ("bad", 0)],
)
def test_elapsed_times_parse(text: str, seconds: int) -> None:
    assert core.parse_etime(text) == seconds


def test_durations_read_at_a_glance() -> None:
    assert [core.format_seconds(s) for s in (5, 65, 3725, 90061)] == [
        "5 s",
        "1m 05s",
        "1h 02m",
        "1d 01h",
    ]


def test_the_psql_script_quotes_the_checkout_and_runs_make_dev_psql() -> None:
    script = core.psql_script(Path("/Users/dev/my repo"), "/opt/homebrew/bin:/usr/bin")
    assert script.splitlines() == [
        "#!/bin/bash",
        "# Written by the ComplianceWatch control panel: psql into the dev database.",
        "export PATH=/opt/homebrew/bin:/usr/bin",
        "cd '/Users/dev/my repo' || exit 1",
        "exec make dev-psql",
    ]


def test_backups_list_newest_first_with_their_size_and_skip_empty_or_odd_ones(
    tmp_path: Path,
) -> None:
    backups = tmp_path / "var" / "backups"
    backups.mkdir(parents=True)
    for index, (name, size) in enumerate(
        (
            ("20261001T000000Z.dump", 2_400_000),
            ("20261005T000000Z.dump", 4),
            ("x;y.dump", 4),
            # A failed or cancelled make dev-backup leaves its newest dump empty
            ("20261006T000000Z.dump", 0),
        )
    ):
        path = backups / name
        path.write_bytes(b"d" * size)
        stamp = 1_791_000_000 + index * 60
        os.utime(path, (stamp, stamp))
    dumps = core.list_backups(tmp_path)
    assert dumps == [
        core.Dump("var/backups/20261005T000000Z.dump", 4, 1_791_000_060),
        core.Dump("var/backups/20261001T000000Z.dump", 2_400_000, 1_791_000_000),
    ]
    assert (
        dumps[1].describe(1_791_000_000 + 7_200)
        == "20261001T000000Z.dump  ·  2.3 MB  ·  2h 00m ago"
    )
    assert core.list_backups(tmp_path / "missing") == []


def test_sizes_read_at_a_glance() -> None:
    assert [core.format_size(n) for n in (4, 2048, 2_400_000, 3 * 1024**3)] == [
        "4 B",
        "2.0 kB",
        "2.3 MB",
        "3.0 GB",
    ]


COMPOSE = """\
name: compliancewatch
services:
  postgres:
    volumes:
      - postgres_data:/var/lib/postgresql/data
  grafana:
    volumes:
      - grafana_data:/var/lib/grafana

volumes:
  # every named volume of the stack
  postgres_data:
  redis_data:
  grafana_data: {}
"""


def test_the_named_volumes_come_from_the_compose_file() -> None:
    assert core.parse_compose_volumes(COMPOSE) == ["postgres_data", "redis_data", "grafana_data"]
    assert core.parse_compose_volumes("services: {}\n") == []
    root = Path("/Users/dev/cw")
    assert core.compose_project_name(COMPOSE, {}, {}, root) == "compliancewatch"
    env_file = {"COMPOSE_PROJECT_NAME": "cw2"}
    assert core.compose_project_name(COMPOSE, env_file, {}, root) == "cw2"
    environ = {"COMPOSE_PROJECT_NAME": "cw3"}
    assert core.compose_project_name(COMPOSE, env_file, environ, root) == "cw3"
    assert core.compose_project_name("services: {}\n", {}, {}, root) == "cw"


def test_the_build_the_window_shows() -> None:
    assert core.describe_build({}) == "Panel: this checkout's tools/control-panel"
    built = {"built": "2026-10-06 18:40", "commit": "3db3bc7", "files": "a1b2c3d4e5f6"}
    assert core.describe_build(built) == "Panel build 2026-10-06 18:40 · commit 3db3bc7"
    outside = {**built, "commit": "none"}
    assert core.describe_build(outside) == (
        "Panel build 2026-10-06 18:40 · files a1b2c3d4e5f6, no commit"
    )


def test_the_end_of_a_log_is_read_without_its_colour_codes(tmp_path: Path) -> None:
    log = tmp_path / "worker.log"
    log.write_text("".join(f"\x1b[2mline {n}\x1b[0m\n" for n in range(40)))
    assert core.tail_lines(log, 3) == ["line 37", "line 38", "line 39"]
    assert core.tail_lines(tmp_path / "missing.log", 3) == []


def test_the_program_environment_puts_homebrew_first_and_drops_the_repo_override() -> None:
    env = core.program_env({"PATH": "/usr/bin:/bin", "HOME": "/Users/dev", core.REPO_ENV: "/x"})
    assert env["PATH"] == "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/Users/dev/.local/bin"
    assert env["PYTHONUNBUFFERED"] == "1"
    assert core.REPO_ENV not in env


def test_the_program_environment_drops_what_make_would_read_and_keeps_the_crawl_off() -> None:
    # make control-panel ARGS=--destructive reaches the panel as MAKEFLAGS and ARGS
    launched = {
        "PATH": "/usr/bin",
        "ARGS": "--destructive",
        "MAKEFLAGS": " -- ARGS=--destructive",
        "MFLAGS": "-s",
        "GNUMAKEFLAGS": "-s",
        "MAKELEVEL": "1",
        "MAKEOVERRIDES": "${-*-command-variables-*-}",
        "SERVICE": "pipeline",
        "PROC": "web",
        "FOLLOW": "1",
        "FILE": "x.dump",
        "WEB": "0",
        "CW_PIPELINE_CRAWL_ENABLED": "true",
        "WEB_PORT": "3200",
    }
    env = core.program_env(launched)
    assert not set(core.DROPPED_VARIABLES) & set(env)
    assert env["CW_PIPELINE_CRAWL_ENABLED"] == "false"
    assert env["WEB_PORT"] == "3200"
    assert core.command_problems(("make", "product-check"), env, complete_env=True) == []
    assert core.repo_root({core.REPO_ENV: "/tmp/checkout"}) == Path("/tmp/checkout").resolve()
    assert core.repo_root({}) == Path(core.__file__).resolve().parents[2]
