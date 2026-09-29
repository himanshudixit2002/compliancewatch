"""The migration lint: static rules over migration files, catalog rules over catalog rows."""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from check_migrations import (
    CONFIG,
    ROOT,
    LintConfig,
    Policy,
    Table,
    TenantColumn,
    catalog_problems,
    libpq_dsn,
    load_config,
    parse_config,
    parse_migration,
    static_problems,
    tenant_checked,
)

SCRIPT = Path(__file__).resolve().parents[1] / "check_migrations.py"

# ---------------------------------------------------------------------------------- static mode

UNDO = 'op.drop_table("thing")'


def migration(
    revision: str,
    down: str | None,
    upgrade: str = 'op.create_table("thing")',
    downgrade: str = UNDO,
    header: str = "",
) -> str:
    """A migration file in the repository's shape, with the given function bodies."""

    def body(code: str) -> str:
        return textwrap.indent(textwrap.dedent(code).strip(), "    ")

    down_literal = "None" if down is None else f'"{down}"'
    return (
        '"""a migration"""\n\n'
        "import sqlalchemy as sa\n"
        "from alembic import op\n\n"
        f'revision: str = "{revision}"\n'
        f"down_revision: str | None = {down_literal}\n"
        f"{textwrap.dedent(header).strip()}\n\n\n"
        f"def upgrade() -> None:\n{body(upgrade)}\n\n\n"
        f"def downgrade() -> None:\n{body(downgrade)}\n"
    )


def write(root: Path, service: str, name: str, source: str) -> None:
    versions = root / "services" / service / "migrations" / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    (versions / name).write_text(source, encoding="utf-8")


def problems_of(source: str, name: str = "20260929_0002_change.py") -> tuple[str, ...]:
    return parse_migration(name, source).problems


def test_the_repository_migrations_pass() -> None:
    total, problems = static_problems(ROOT)
    assert problems == []
    assert total > 0


def test_a_linear_chain_passes(tmp_path: Path) -> None:
    write(tmp_path, "svc", "20260929_0001_first.py", migration("0001", None))
    write(tmp_path, "svc", "20260929_0002_second.py", migration("0002", "0001"))
    assert static_problems(tmp_path) == (2, [])


def test_two_heads_fail(tmp_path: Path) -> None:
    write(tmp_path, "svc", "20260929_0001_first.py", migration("0001", None))
    write(tmp_path, "svc", "20260929_0002_mine.py", migration("0002", "0001"))
    write(tmp_path, "svc", "20260929_0003_theirs.py", migration("0003", "0001"))
    _, problems = static_problems(tmp_path)
    assert problems == [
        "services/svc/migrations/versions: 2 heads (0002, 0003); exactly one is allowed, so "
        "renumber the later migration onto the current head"
    ]


def test_a_duplicate_revision_fails(tmp_path: Path) -> None:
    write(tmp_path, "svc", "20260929_0001_first.py", migration("0001", None))
    write(tmp_path, "svc", "20260929_0002_mine.py", migration("0002", "0001"))
    write(tmp_path, "svc", "20260930_0002_theirs.py", migration("0002", "0001"))
    _, problems = static_problems(tmp_path)
    assert any("revision '0002' appears 2 times" in problem for problem in problems)


def test_services_are_checked_independently(tmp_path: Path) -> None:
    write(tmp_path, "one", "20260929_0001_first.py", migration("0001", None))
    write(tmp_path, "two", "20260929_0001_first.py", migration("0001", None))
    assert static_problems(tmp_path) == (2, [])


def test_a_down_revision_that_matches_nothing_fails(tmp_path: Path) -> None:
    write(tmp_path, "svc", "20260929_0002_orphan.py", migration("0002", "0001"))
    _, problems = static_problems(tmp_path)
    assert any("down_revision '0001' matches no revision" in problem for problem in problems)


def test_a_file_name_that_differs_from_the_revision_fails() -> None:
    problems = problems_of(migration("0003", "0001"), name="20260929_0002_change.py")
    assert problems == (
        "20260929_0002_change.py: the file number 0002 differs from revision '0003'",
    )


@pytest.mark.parametrize(
    "name", ["2026-09-29_0002_change.py", "20260929_2_change.py", "20260929_0002_Change.py"]
)
def test_a_file_name_outside_the_pattern_fails(name: str) -> None:
    assert problems_of(migration("0002", "0001"), name=name) == (
        f"{name}: the file name does not match YYYYMMDD_NNNN_slug.py",
    )


def test_a_file_name_with_an_impossible_date_fails() -> None:
    problems = problems_of(migration("0002", "0001"), name="20261399_0002_change.py")
    assert problems == ("20261399_0002_change.py: 20261399 is not a date",)


def test_a_missing_revision_fails() -> None:
    source = migration("0002", "0001").replace('revision: str = "0002"', "")
    assert "20260929_0002_change.py: no string revision" in problems_of(source)


@pytest.mark.parametrize("body", ["pass", "...", '"""Nothing to undo."""'])
def test_an_empty_downgrade_fails(body: str) -> None:
    assert problems_of(migration("0002", "0001", downgrade=body)) == (
        "20260929_0002_change.py: downgrade() is empty; undo the upgrade or mark it "
        "'# irreversible: <reason>'",
    )


def test_an_empty_downgrade_marked_irreversible_passes() -> None:
    body = "# irreversible: the merged rows cannot be split again\npass"
    assert problems_of(migration("0002", "0001", downgrade=body)) == ()


def test_an_irreversible_marker_needs_a_reason() -> None:
    body = "# irreversible:\npass"
    assert problems_of(migration("0002", "0001", downgrade=body)) != ()


def test_a_missing_downgrade_fails() -> None:
    source = migration("0002", "0001").split("def downgrade")[0]
    assert "20260929_0002_change.py: no downgrade()" in problems_of(source)


def test_drop_column_without_the_contract_marker_fails() -> None:
    upgrade = 'op.drop_column("thing", "legacy")'
    problems = problems_of(migration("0002", "0001", upgrade=upgrade))
    assert len(problems) == 1
    assert "drop_column in upgrade() is a contract step" in problems[0]


def test_drop_column_with_the_contract_marker_passes() -> None:
    upgrade = """
        # contract: nothing has read thing.legacy since 0001 shipped
        op.drop_column("thing", "legacy")
        """
    assert problems_of(migration("0002", "0001", upgrade=upgrade)) == ()


def test_the_marker_may_head_a_comment_block() -> None:
    upgrade = """
        # contract: nothing has read thing.legacy since 0001 shipped
        # (the reader moved to thing.current in the previous release)
        op.drop_column("thing", "legacy")
        """
    assert problems_of(migration("0002", "0001", upgrade=upgrade)) == ()


@pytest.mark.parametrize(
    "call",
    [
        'op.drop_table("thing")',
        'op.rename_table("thing", "other")',
        'op.alter_column("thing", "a", new_column_name="b")',
        'op.alter_column("thing", "a", nullable=False)',
        'op.execute("ALTER TABLE thing DROP COLUMN legacy")',
        'op.execute("drop table thing")',
        'op.execute(sa.text("ALTER TABLE thing RENAME TO other"))',
        'op.execute("ALTER TABLE thing ALTER COLUMN a SET  NOT NULL")',
        'op.get_bind().exec_driver_sql("DROP TABLE thing")',
    ],
)
def test_every_contract_step_needs_the_marker(call: str) -> None:
    unmarked = problems_of(migration("0002", "0001", upgrade=call))
    assert len(unmarked) == 1
    assert "is a contract step" in unmarked[0]
    marked = f"# contract: the old shape has no reader\n{call}"
    assert problems_of(migration("0002", "0001", upgrade=marked)) == ()


@pytest.mark.parametrize(
    "call",
    [
        'op.add_column("thing", sa.Column("a", sa.Text(), nullable=False, server_default=""))',
        'op.alter_column("thing", "a", nullable=True)',
        'op.drop_constraint("ck_thing_kind", "thing", type_="check")',
        'op.execute("CREATE INDEX ix_thing_a ON thing (a)")',
    ],
)
def test_expand_steps_need_no_marker(call: str) -> None:
    assert problems_of(migration("0002", "0001", upgrade=call)) == ()


def test_sql_in_a_module_constant_is_read() -> None:
    source = migration(
        "0002", "0001", upgrade="op.execute(DROP_LEGACY)", header='DROP_LEGACY = "DROP TABLE x"'
    )
    assert len(problems_of(source)) == 1


def test_a_step_inside_a_helper_is_found_and_the_marker_may_sit_on_the_call() -> None:
    helper = textwrap.dedent(
        """
        def _drop_legacy() -> None:
            op.drop_column("thing", "legacy")
        """
    )
    unmarked = migration("0002", "0001", upgrade="_drop_legacy()", header=helper)
    assert len(problems_of(unmarked)) == 1
    marked = migration(
        "0002", "0001", upgrade="# contract: no reader left\n_drop_legacy()", header=helper
    )
    assert problems_of(marked) == ()


def test_the_marker_may_sit_above_a_loop() -> None:
    upgrade = """
        # contract: both tables were emptied and unused since 0001
        for table in ("a", "b"):
            op.drop_table(table)
        """
    assert problems_of(migration("0002", "0001", upgrade=upgrade)) == ()


def test_contract_steps_in_downgrade_need_no_marker() -> None:
    downgrade = 'op.drop_column("thing", "added")'
    assert problems_of(migration("0002", "0001", downgrade=downgrade)) == ()


def test_the_cli_reports_problems_and_exits_non_zero(tmp_path: Path) -> None:
    upgrade = 'op.drop_column("thing", "legacy")'
    write(tmp_path, "svc", "20260929_0001_first.py", migration("0001", None, upgrade=upgrade))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "static", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "drop_column in upgrade() is a contract step" in result.stderr


def test_the_cli_passes_the_repository() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "static"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "one head per service" in result.stdout


# --------------------------------------------------------------------------------- catalog mode

# The policy expressions exactly as Postgres 16 deparses them into pg_policies.
TENANT_CHECK = (
    "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)"
)
NO_NULLIF = "(tenant_id = (current_setting('app.tenant_id'::text, true))::uuid)"
OTHER_SETTING = "(tenant_id = (NULLIF(current_setting('app.user_id'::text, true), ''::text))::uuid)"
ON_ID = "(id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)"
OPEN = "true"

ISOLATION = Policy("thing_tenant_isolation", "ALL", True, TENANT_CHECK, TENANT_CHECK)
CONFIG_TEXT = """
[schemas]
tenant = ["identity", "applicability"]
global = ["rulebook"]

[[exemptions]]
table = "*.outbox_event"
reason = "The relay reads across tenants."

[[exemptions]]
table = "applicability.business_directory"
kind = "routing_directory"
reason = "Routes work to the tenant that owns a business."
"""


@pytest.fixture
def config() -> LintConfig:
    return parse_config(CONFIG_TEXT)


def tenant_table(
    name: str = "thing",
    schema: str = "identity",
    *,
    tenant_id: TenantColumn = "not_null",
    row_security: bool = True,
    force_row_security: bool = True,
    policies: tuple[Policy, ...] = (ISOLATION,),
) -> Table:
    return Table(schema, name, tenant_id, row_security, force_row_security, policies)


def directory(
    *policies: Policy, tenant_id: TenantColumn = "not_null", force_row_security: bool = True
) -> Table:
    return tenant_table(
        "business_directory",
        "applicability",
        tenant_id=tenant_id,
        force_row_security=force_row_security,
        policies=policies,
    )


def baseline() -> list[Table]:
    """Tables that satisfy the config above, so each test adds only its own problem."""
    return [
        Table("identity", "outbox_event", "nullable", False, False),
        Table("rulebook", "rule", "absent", False, False),
        directory(
            Policy("read", "SELECT", True, OPEN, None),
            Policy("write", "ALL", True, TENANT_CHECK, TENANT_CHECK),
        ),
    ]


def test_a_catalog_that_follows_the_rules_passes(config: LintConfig) -> None:
    assert catalog_problems([*baseline(), tenant_table()], config) == []


@pytest.mark.parametrize(
    "expression",
    [
        TENANT_CHECK,
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid "
        "AND archived = false)",
    ],
)
def test_the_tenant_check_is_recognised(expression: str) -> None:
    assert tenant_checked(expression)


@pytest.mark.parametrize("expression", [None, OPEN, NO_NULLIF, OTHER_SETTING, ON_ID])
def test_other_expressions_are_not_a_tenant_check(expression: str | None) -> None:
    assert not tenant_checked(expression)


def test_a_tenant_table_without_force_fails(config: LintConfig) -> None:
    problems = catalog_problems([*baseline(), tenant_table(force_row_security=False)], config)
    assert problems == [
        "identity.thing: R1: row-level security is not forced, so the table owner bypasses it"
    ]


def test_a_tenant_table_without_row_security_fails(config: LintConfig) -> None:
    table = tenant_table(row_security=False, force_row_security=False)
    problems = catalog_problems([*baseline(), table], config)
    assert problems == ["identity.thing: R1: row-level security is not enabled"]


def test_a_tenant_table_without_a_policy_fails(config: LintConfig) -> None:
    problems = catalog_problems([*baseline(), tenant_table(policies=())], config)
    assert problems == ["identity.thing: R1: no policy for ALL commands"]


def test_a_policy_without_nullif_fails(config: LintConfig) -> None:
    policy = Policy("thing_tenant_isolation", "ALL", True, NO_NULLIF, NO_NULLIF)
    problems = catalog_problems([*baseline(), tenant_table(policies=(policy,))], config)
    assert len(problems) == 2
    assert all("does not compare tenant_id with NULLIF" in problem for problem in problems)


def test_using_without_with_check_fails(config: LintConfig) -> None:
    policy = Policy("thing_tenant_isolation", "ALL", True, TENANT_CHECK, None)
    problems = catalog_problems([*baseline(), tenant_table(policies=(policy,))], config)
    assert problems == [
        "identity.thing: R1: policy thing_tenant_isolation has USING but no WITH CHECK"
    ]


def test_a_policy_for_one_command_only_does_not_satisfy_r1(config: LintConfig) -> None:
    policy = Policy("thing_select", "SELECT", True, TENANT_CHECK, None)
    problems = catalog_problems([*baseline(), tenant_table(policies=(policy,))], config)
    assert problems == ["identity.thing: R1: no policy for ALL commands"]


def test_an_extra_open_policy_on_a_tenant_table_fails(config: LintConfig) -> None:
    extra = Policy("thing_read_all", "SELECT", True, OPEN, None)
    problems = catalog_problems([*baseline(), tenant_table(policies=(ISOLATION, extra))], config)
    assert len(problems) == 1
    assert "policy thing_read_all (FOR SELECT) admits rows without the tenant check" in problems[0]


def test_a_restrictive_policy_is_not_a_leak(config: LintConfig) -> None:
    narrowing = Policy("thing_not_archived", "SELECT", False, "(archived = false)", None)
    tables = [*baseline(), tenant_table(policies=(ISOLATION, narrowing))]
    assert catalog_problems(tables, config) == []


def test_a_nullable_tenant_id_that_is_not_exempt_fails(config: LintConfig) -> None:
    problems = catalog_problems([*baseline(), tenant_table(tenant_id="nullable")], config)
    assert problems == ["identity.thing: R3: tenant_id is nullable and the table is not exempt"]


def test_a_nullable_tenant_id_in_a_global_schema_fails_too(config: LintConfig) -> None:
    table = Table("rulebook", "usage", "nullable", False, False)
    assert catalog_problems([*baseline(), table], config) == [
        "rulebook.usage: R3: tenant_id is nullable and the table is not exempt"
    ]


def test_a_tenant_schema_table_without_tenant_id_fails(config: LintConfig) -> None:
    table = Table("identity", "lookup", "absent", False, False)
    assert catalog_problems([*baseline(), table], config) == [
        "identity.lookup: R2: a table in tenant schema identity has no tenant_id"
    ]


def test_a_global_schema_table_without_tenant_id_passes(config: LintConfig) -> None:
    table = Table("rulebook", "document", "absent", False, False)
    assert catalog_problems([*baseline(), table], config) == []


def test_a_stale_exemption_fails(config: LintConfig) -> None:
    tables = [table for table in baseline() if table.name != "outbox_event"]
    assert catalog_problems(tables, config) == [
        "exemption *.outbox_event: R4: matches no table; remove it"
    ]


def test_a_table_in_an_unknown_schema_fails(config: LintConfig) -> None:
    table = Table("public", "scratch", "absent", False, False)
    assert catalog_problems([*baseline(), table], config) == [
        "public.scratch: schema public is neither a tenant nor a global schema in "
        "migration_lint.toml"
    ]


def test_a_routing_directory_with_tenant_checked_writes_passes(config: LintConfig) -> None:
    tables = [table for table in baseline() if table.name != "business_directory"]
    split_writes = directory(
        Policy("read", "SELECT", True, OPEN, None),
        Policy("insert", "INSERT", True, None, TENANT_CHECK),
        Policy("update", "UPDATE", True, TENANT_CHECK, TENANT_CHECK),
        Policy("delete", "DELETE", True, TENANT_CHECK, None),
    )
    assert catalog_problems([*tables, split_writes], config) == []


def test_a_routing_directory_with_an_open_write_policy_fails(config: LintConfig) -> None:
    tables = [table for table in baseline() if table.name != "business_directory"]
    leaky = directory(
        Policy("read", "SELECT", True, OPEN, None),
        Policy("write", "ALL", True, TENANT_CHECK, TENANT_CHECK),
        Policy("backfill", "INSERT", True, None, OPEN),
    )
    assert catalog_problems([*tables, leaky], config) == [
        "applicability.business_directory: R1: write policy backfill (FOR INSERT) needs a WITH "
        "CHECK that compares tenant_id with the app.tenant_id setting"
    ]


def test_a_routing_directory_still_needs_forced_row_security(config: LintConfig) -> None:
    tables = [table for table in baseline() if table.name != "business_directory"]
    table = directory(
        Policy("write", "ALL", True, TENANT_CHECK, TENANT_CHECK), force_row_security=False
    )
    assert catalog_problems([*tables, table], config) == [
        "applicability.business_directory: R1: row-level security is not forced, so the table "
        "owner bypasses it"
    ]


def test_a_routing_directory_needs_an_insert_policy(config: LintConfig) -> None:
    tables = [table for table in baseline() if table.name != "business_directory"]
    table = directory(Policy("read", "SELECT", True, OPEN, None))
    assert catalog_problems([*tables, table], config) == [
        "applicability.business_directory: R1: no policy admits INSERT"
    ]


def test_a_routing_directory_needs_a_not_null_tenant_id(config: LintConfig) -> None:
    tables = [table for table in baseline() if table.name != "business_directory"]
    table = directory(
        Policy("write", "ALL", True, TENANT_CHECK, TENANT_CHECK), tenant_id="nullable"
    )
    assert catalog_problems([*tables, table], config) == [
        "applicability.business_directory: routing_directory needs a NOT NULL tenant_id"
    ]


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ('table = "identity.thing"', "a reason is required"),
        ('table = "thing"\nreason = "x"', "name the table as schema.table"),
        ('table = "identity.thing"\nreason = "x"\nkind = "skip"', "kind must be one of"),
    ],
)
def test_a_malformed_exemption_is_refused(entry: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_config(f"[[exemptions]]\n{entry}\n")


def test_an_exemption_listed_twice_is_refused() -> None:
    entry = '[[exemptions]]\ntable = "identity.thing"\nreason = "x"\n'
    with pytest.raises(ValueError, match="listed twice"):
        parse_config(entry * 2)


def test_a_schema_in_both_groups_is_refused() -> None:
    with pytest.raises(ValueError, match="both tenant and global"):
        parse_config('[schemas]\ntenant = ["qa"]\nglobal = ["qa"]\n')


def test_the_repository_config_seeds_the_exemptions_with_reasons() -> None:
    config = load_config(CONFIG)
    seeded = {exemption.table: exemption for exemption in config.exemptions}
    assert {"*.outbox_event", "*.processed_event", "*.alembic_version"} <= set(seeded)
    assert "tenant_id is NULL for regulatory calls" in seeded["llm_gateway.cost_ledger"].reason
    assert config.tenant_schemas == {
        "identity",
        "profile",
        "obligation",
        "notification",
        "applicability",
        "qa",
    }
    assert {"rulebook", "pipeline", "llm_gateway", "eval"} <= config.global_schemas


def test_the_sqlalchemy_url_form_is_accepted() -> None:
    assert libpq_dsn("postgresql+psycopg://cw:cw@localhost:5432/db") == (
        "postgresql://cw:cw@localhost:5432/db"
    )
    assert libpq_dsn("postgresql://cw:cw@localhost/db") == "postgresql://cw:cw@localhost/db"
