"""Migration lint: safe migration files, and tenant isolation in the migrated catalog.

``static`` needs no database. For every ``services/*/migrations/versions`` directory it checks
that revision ids are unique with exactly one head, that each file is named
``YYYYMMDD_NNNN_slug.py`` with NNNN equal to its ``revision`` and a ``down_revision`` that
resolves, that ``downgrade()`` does something unless it is marked ``# irreversible: <reason>``,
and that every contract step in ``upgrade()`` (dropping or renaming a table or column, or making
a column NOT NULL) carries a ``# contract: <reason>`` comment on the line above: expand first,
contract in a later release once no running code reads the old shape (guide section 17).

``catalog --dsn`` reads pg_class, pg_attribute and pg_policies of a database every service has
migrated, with the rules and exemptions of ``migration_lint.toml``:

- R1: a table with a NOT NULL tenant_id has row-level security enabled and forced, and a policy
  for ALL commands whose USING and WITH CHECK both compare tenant_id with
  ``NULLIF(current_setting('app.tenant_id', true), '')``. No other permissive policy may let
  rows through without that comparison.
- R2: every table in a tenant schema has a tenant_id column.
- R3: a nullable tenant_id is allowed only on an exempt table.
- R4: every exemption matches at least one table.

An exemption of kind ``routing_directory`` does not skip R1: reads may cross tenants (a
directory that routes work), but every policy that admits a write must hold the tenant check.

Every check is a pure function over parsed files or catalog rows; only ``read_catalog`` and
``main`` touch the database or the file system. Run as ``make migrations-check`` and
``make migrations-catalog``.
"""

import argparse
import ast
import fnmatch
import re
import sys
import tomllib
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    import psycopg

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(__file__).resolve().with_name("migration_lint.toml")

FILENAME = re.compile(r"^(?P<date>\d{8})_(?P<number>\d{4})_(?P<slug>[a-z0-9][a-z0-9_]*)\.py$")
CONTRACT_MARKER = re.compile(r"^#\s*contract:\s*\S")
IRREVERSIBLE_MARKER = re.compile(r"^#\s*irreversible:\s*\S")
CONTRACT_OPERATIONS = frozenset({"drop_column", "drop_table", "rename_table"})
CONTRACT_SQL = re.compile(r"\b(DROP\s+COLUMN|DROP\s+TABLE|RENAME|SET\s+NOT\s+NULL)\b", re.I)
SQL_CALLS = frozenset({"execute", "exec_driver_sql"})

TENANT_SETTING = "nullif(current_setting('app.tenant_id',true),'')"
EXEMPT = "exempt"
ROUTING_DIRECTORY = "routing_directory"
KINDS = (EXEMPT, ROUTING_DIRECTORY)
WRITE_COMMANDS = ("INSERT", "UPDATE", "DELETE")

type TenantColumn = Literal["absent", "nullable", "not_null"]


# ---------------------------------------------------------------------------------- static mode


@dataclass(frozen=True)
class Migration:
    """One migration file, as far as the chain checks need it."""

    name: str
    revision: str | None
    down_revisions: tuple[str, ...]
    problems: tuple[str, ...]


def _assignments(tree: ast.Module) -> Iterator[tuple[str, ast.expr]]:
    """Module-level ``name = value`` and ``name: type = value`` bindings."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if isinstance(target, ast.Name):
            yield target.id, value


def _module_strings(tree: ast.Module) -> dict[str, str]:
    """Module-level names bound to a string, so ``op.execute(SQL)`` can be read."""
    return {
        name: value.value
        for name, value in _assignments(tree)
        if isinstance(value, ast.Constant) and isinstance(value.value, str)
    }


def _literal(value: ast.expr) -> object:
    try:
        return ast.literal_eval(value)
    except (ValueError, TypeError, SyntaxError):
        return value


def _revision_values(tree: ast.Module) -> tuple[object, object]:
    """The literal values of ``revision`` and ``down_revision`` (``...`` when absent)."""
    values = {
        name: _literal(value)
        for name, value in _assignments(tree)
        if name in {"revision", "down_revision"}
    }
    return values.get("revision", ...), values.get("down_revision", ...)


def _is_empty(function: ast.FunctionDef) -> bool:
    """A body of nothing but ``pass``, ``...`` or a docstring."""
    for statement in function.body:
        if isinstance(statement, ast.Pass):
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            continue
        return False
    return True


def _comment_block_above(lines: Sequence[str], line: int) -> Iterator[str]:
    """The comment lines directly above 1-based ``line``, nearest first."""
    index = line - 2
    while index >= 0 and lines[index].strip().startswith("#"):
        yield lines[index].strip()
        index -= 1


def _marked(lines: Sequence[str], line: int, marker: re.Pattern[str]) -> bool:
    return any(marker.match(comment) for comment in _comment_block_above(lines, line))


def _sql_text(node: ast.expr, strings: dict[str, str]) -> str:
    """Every string literal inside an ``execute`` argument, module constants resolved."""
    parts: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            parts.append(child.value)
        elif isinstance(child, ast.Name) and child.id in strings:
            parts.append(strings[child.id])
    return " ".join(parts)


def _contract_step(call: ast.Call, strings: dict[str, str]) -> str | None:
    """A description of the contract step ``call`` performs, or None for anything else."""
    if not isinstance(call.func, ast.Attribute):
        return None
    name = call.func.attr
    if name in CONTRACT_OPERATIONS:
        return name
    if name == "alter_column":
        for keyword in call.keywords:
            if keyword.arg == "new_column_name":
                return "alter_column(new_column_name=...)"
            if (
                keyword.arg == "nullable"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is False
            ):
                return "alter_column(nullable=False)"
        return None
    if name in SQL_CALLS and call.args:
        found = CONTRACT_SQL.search(_sql_text(call.args[0], strings))
        if found:
            return f"{name}({' '.join(found.group(1).upper().split())})"
    return None


def _contract_steps(
    node: ast.AST,
    functions: dict[str, ast.FunctionDef],
    strings: dict[str, str],
    seen: set[str],
) -> Iterator[tuple[int, str]]:
    """(line, description) of every contract step under ``node``, following module helpers."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        step = _contract_step(child, strings)
        if step is not None:
            yield child.lineno, step
        elif isinstance(child.func, ast.Name) and child.func.id in functions:
            helper = child.func.id
            if helper not in seen:
                yield from _contract_steps(functions[helper], functions, strings, seen | {helper})


def _revision_problems(name: str, revision: object, down: object) -> list[str]:
    problems: list[str] = []
    if not isinstance(revision, str):
        problems.append(f"{name}: no string revision")
    if down is ...:
        problems.append(f"{name}: no down_revision (None for the first migration)")
    elif not (
        down is None
        or isinstance(down, str)
        or (isinstance(down, tuple) and all(isinstance(item, str) for item in down))
    ):
        problems.append(f"{name}: down_revision must be None, a string or a tuple of strings")
    matched = FILENAME.match(name)
    if matched is None:
        problems.append(f"{name}: the file name does not match YYYYMMDD_NNNN_slug.py")
        return problems
    try:
        datetime.strptime(matched["date"], "%Y%m%d")
    except ValueError:
        problems.append(f"{name}: {matched['date']} is not a date")
    if isinstance(revision, str) and matched["number"] != revision:
        problems.append(
            f"{name}: the file number {matched['number']} differs from revision {revision!r}"
        )
    return problems


def _downgrade_problems(
    name: str, lines: Sequence[str], downgrade: ast.FunctionDef | None
) -> list[str]:
    if downgrade is None:
        return [f"{name}: no downgrade()"]
    if not _is_empty(downgrade):
        return []
    body = lines[downgrade.lineno - 1 : downgrade.end_lineno]
    if any(IRREVERSIBLE_MARKER.match(line.strip()) for line in body):
        return []
    if _marked(lines, downgrade.lineno, IRREVERSIBLE_MARKER):
        return []
    return [f"{name}: downgrade() is empty; undo the upgrade or mark it '# irreversible: <reason>'"]


def _contract_problems(
    name: str, tree: ast.Module, lines: Sequence[str], functions: dict[str, ast.FunctionDef]
) -> list[str]:
    upgrade = functions.get("upgrade")
    if upgrade is None:
        return [f"{name}: no upgrade()"]
    strings = _module_strings(tree)
    problems: list[str] = []
    for statement in upgrade.body:
        # The marker may sit above the step itself or above the statement of upgrade() that
        # reaches it (a loop, a with block, or a call to a helper in the same file).
        for line, step in _contract_steps(statement, functions, strings, {"upgrade"}):
            if _marked(lines, line, CONTRACT_MARKER):
                continue
            if _marked(lines, statement.lineno, CONTRACT_MARKER):
                continue
            problems.append(
                f"{name}:{line}: {step} in upgrade() is a contract step; expand first and put "
                "'# contract: <reason>' on the line above once nothing reads the old shape"
            )
    return problems


def parse_migration(name: str, source: str) -> Migration:
    """Parse one migration file and collect the problems that concern the file alone."""
    try:
        tree = ast.parse(source, filename=name)
    except SyntaxError as error:
        return Migration(name, None, (), (f"{name}: does not parse ({error.msg})",))
    lines = source.splitlines()
    revision, down = _revision_values(tree)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    problems = [
        *_revision_problems(name, revision, down),
        *_downgrade_problems(name, lines, functions.get("downgrade")),
        *_contract_problems(name, tree, lines, functions),
    ]
    if isinstance(down, str):
        down_revisions: tuple[str, ...] = (down,)
    elif isinstance(down, tuple):
        down_revisions = tuple(item for item in down if isinstance(item, str))
    else:
        down_revisions = ()
    return Migration(
        name, revision if isinstance(revision, str) else None, down_revisions, tuple(problems)
    )


def chain_problems(service: str, migrations: Sequence[Migration]) -> list[str]:
    """Unique revisions, resolvable down_revisions and exactly one head in one directory."""
    problems: list[str] = []
    counts = Counter(m.revision for m in migrations if m.revision is not None)
    for revision, count in sorted(counts.items()):
        if count > 1:
            names = ", ".join(m.name for m in migrations if m.revision == revision)
            problems.append(f"{service}: revision {revision!r} appears {count} times ({names})")
    revisions = set(counts)
    referenced: set[str] = set()
    for migration in migrations:
        for down in migration.down_revisions:
            referenced.add(down)
            if down not in revisions:
                problems.append(
                    f"{service}: {migration.name}: down_revision {down!r} matches no revision"
                )
    heads = sorted(revisions - referenced)
    if migrations and len(heads) != 1:
        problems.append(
            f"{service}: {len(heads)} heads ({', '.join(heads) or 'none'}); exactly one is "
            "allowed, so renumber the later migration onto the current head"
        )
    return problems


def migrations_of(versions: Path) -> list[Migration]:
    return [
        parse_migration(path.name, path.read_text(encoding="utf-8"))
        for path in sorted(versions.glob("*.py"))
        if path.name != "__init__.py"
    ]


def static_problems(root: Path = ROOT) -> tuple[int, list[str]]:
    """(number of migrations read, problems) over every service under ``root``."""
    problems: list[str] = []
    total = 0
    for versions in sorted(root.glob("services/*/migrations/versions")):
        label = versions.relative_to(root).as_posix()
        migrations = migrations_of(versions)
        total += len(migrations)
        for migration in migrations:
            problems.extend(f"{label}/{problem}" for problem in migration.problems)
        problems.extend(chain_problems(label, migrations))
    return total, problems


# --------------------------------------------------------------------------------- catalog mode


@dataclass(frozen=True)
class Policy:
    """One row of pg_policies. ``qual`` is USING and ``with_check`` is WITH CHECK, deparsed."""

    name: str
    command: str
    permissive: bool
    qual: str | None
    with_check: str | None


@dataclass(frozen=True)
class Table:
    """What the rules need to know about one table."""

    schema: str
    name: str
    tenant_id: TenantColumn
    row_security: bool
    force_row_security: bool
    policies: tuple[Policy, ...] = ()

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}"


@dataclass(frozen=True)
class Exemption:
    table: str
    reason: str
    kind: str = EXEMPT

    def matches(self, qualified: str) -> bool:
        return fnmatch.fnmatchcase(qualified, self.table)


@dataclass(frozen=True)
class LintConfig:
    tenant_schemas: frozenset[str]
    global_schemas: frozenset[str]
    exemptions: tuple[Exemption, ...]

    def exemption_for(self, qualified: str) -> Exemption | None:
        return next((e for e in self.exemptions if e.matches(qualified)), None)


def parse_config(text: str) -> LintConfig:
    """Read migration_lint.toml; a malformed entry raises ValueError."""
    data = tomllib.loads(text)
    schemas = data.get("schemas", {})
    tenant = frozenset(schemas.get("tenant", []))
    global_ = frozenset(schemas.get("global", []))
    if tenant & global_:
        raise ValueError(f"schemas both tenant and global: {sorted(tenant & global_)}")
    exemptions: list[Exemption] = []
    for entry in data.get("exemptions", []):
        table = str(entry.get("table", "")).strip()
        reason = " ".join(str(entry.get("reason", "")).split())
        kind = str(entry.get("kind", EXEMPT))
        if "." not in table:
            raise ValueError(f"exemption {table!r}: name the table as schema.table")
        if not reason:
            raise ValueError(f"exemption {table!r}: a reason is required")
        if kind not in KINDS:
            raise ValueError(f"exemption {table!r}: kind must be one of {', '.join(KINDS)}")
        if any(e.table == table for e in exemptions):
            raise ValueError(f"exemption {table!r} is listed twice")
        exemptions.append(Exemption(table, reason, kind))
    return LintConfig(tenant, global_, tuple(exemptions))


def load_config(path: Path = CONFIG) -> LintConfig:
    return parse_config(path.read_text(encoding="utf-8"))


def _normalised(expression: str) -> str:
    return re.sub(r"\s+", "", expression).lower().replace("::text", "")


def tenant_checked(expression: str | None) -> bool:
    """True when the expression compares tenant_id with the app.tenant_id setting."""
    if expression is None:
        return False
    normalised = _normalised(expression)
    if TENANT_SETTING not in normalised:
        return False
    return re.search(r"\btenant_id\b", normalised.replace(TENANT_SETTING, "")) is not None


def _covers(policy: Policy, command: str) -> bool:
    return policy.command in {"ALL", command}


def _row_security_problems(table: Table, rule: str) -> list[str]:
    problems: list[str] = []
    if not table.row_security:
        problems.append(f"{table.qualified}: {rule}: row-level security is not enabled")
    elif not table.force_row_security:
        problems.append(
            f"{table.qualified}: {rule}: row-level security is not forced, so the table owner "
            "bypasses it"
        )
    return problems


def tenant_table_problems(table: Table) -> list[str]:
    """R1 for a table with a NOT NULL tenant_id."""
    problems = _row_security_problems(table, "R1")
    for_all = [p for p in table.policies if p.permissive and p.command == "ALL"]
    compliant = [p for p in for_all if tenant_checked(p.qual) and tenant_checked(p.with_check)]
    reported: list[Policy] = []
    if not compliant:
        reported = for_all
        if not for_all:
            problems.append(f"{table.qualified}: R1: no policy for ALL commands")
        for policy in for_all:
            if not tenant_checked(policy.qual):
                problems.append(
                    f"{table.qualified}: R1: policy {policy.name} USING does not compare "
                    "tenant_id with NULLIF(current_setting('app.tenant_id', true), '')"
                )
            if policy.with_check is None:
                problems.append(
                    f"{table.qualified}: R1: policy {policy.name} has USING but no WITH CHECK"
                )
            elif not tenant_checked(policy.with_check):
                problems.append(
                    f"{table.qualified}: R1: policy {policy.name} WITH CHECK does not compare "
                    "tenant_id with NULLIF(current_setting('app.tenant_id', true), '')"
                )
    # Permissive policies combine with OR, so any other one without the check opens the table.
    for policy in table.policies:
        if not policy.permissive or policy in compliant or policy in reported:
            continue
        expressions = [e for e in (policy.qual, policy.with_check) if e is not None]
        if not all(tenant_checked(e) for e in expressions):
            problems.append(
                f"{table.qualified}: R1: policy {policy.name} (FOR {policy.command}) admits rows "
                "without the tenant check; exempt the table as a routing_directory if that is "
                "the intent"
            )
    return problems


def routing_directory_problems(table: Table) -> list[str]:
    """R1 for a routing directory: reads may cross tenants, writes may not."""
    if table.tenant_id != "not_null":
        return [f"{table.qualified}: routing_directory needs a NOT NULL tenant_id"]
    problems = _row_security_problems(table, "R1")
    writers = [
        p for p in table.policies if p.permissive and any(_covers(p, c) for c in WRITE_COMMANDS)
    ]
    if not any(_covers(p, "INSERT") for p in writers):
        problems.append(f"{table.qualified}: R1: no policy admits INSERT")
    for policy in writers:
        writes_rows = policy.command in {"ALL", "INSERT", "UPDATE"}
        reads_rows = policy.command in {"ALL", "UPDATE", "DELETE"}
        if writes_rows and not tenant_checked(policy.with_check):
            problems.append(
                f"{table.qualified}: R1: write policy {policy.name} (FOR {policy.command}) needs "
                "a WITH CHECK that compares tenant_id with the app.tenant_id setting"
            )
        if reads_rows and not tenant_checked(policy.qual):
            problems.append(
                f"{table.qualified}: R1: write policy {policy.name} (FOR {policy.command}) needs "
                "a USING that compares tenant_id with the app.tenant_id setting"
            )
    return problems


def catalog_problems(tables: Sequence[Table], config: LintConfig) -> list[str]:
    """R1 to R4 over the catalog, plus: every table lives in a schema the config names."""
    known = config.tenant_schemas | config.global_schemas
    problems: list[str] = []
    for table in tables:
        if table.schema not in known:
            problems.append(
                f"{table.qualified}: schema {table.schema} is neither a tenant nor a global "
                "schema in migration_lint.toml"
            )
            continue
        exemption = config.exemption_for(table.qualified)
        if exemption is not None and exemption.kind == ROUTING_DIRECTORY:
            problems.extend(routing_directory_problems(table))
        elif exemption is not None:
            continue
        elif table.tenant_id == "absent":
            if table.schema in config.tenant_schemas:
                problems.append(
                    f"{table.qualified}: R2: a table in tenant schema {table.schema} has no "
                    "tenant_id"
                )
        elif table.tenant_id == "nullable":
            problems.append(
                f"{table.qualified}: R3: tenant_id is nullable and the table is not exempt"
            )
        else:
            problems.extend(tenant_table_problems(table))
    for exemption in config.exemptions:
        if not any(exemption.matches(table.qualified) for table in tables):
            problems.append(f"exemption {exemption.table}: R4: matches no table; remove it")
    return problems


TABLES_SQL = """
SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity, a.attnotnull
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_attribute a
  ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND a.attnum > 0 AND NOT a.attisdropped
WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition
  AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg\\_%'
ORDER BY 1, 2
"""
POLICIES_SQL = """
SELECT schemaname, tablename, policyname, cmd, permissive = 'PERMISSIVE', qual, with_check
FROM pg_policies
ORDER BY 1, 2, 3
"""


def libpq_dsn(dsn: str) -> str:
    """Accept the SQLAlchemy form (postgresql+psycopg://) as well as a plain libpq URL."""
    return re.sub(r"^postgresql\+\w+://", "postgresql://", dsn)


def read_tables(connection: "psycopg.Connection[Any]") -> list[Table]:
    """The tables of every application schema with their tenant column and policies."""
    policies: dict[tuple[str, str], list[Policy]] = {}
    for schema, table, name, command, permissive, qual, check in connection.execute(POLICIES_SQL):
        policies.setdefault((schema, table), []).append(
            Policy(name, command, bool(permissive), qual, check)
        )
    tables: list[Table] = []
    for schema, name, rls, force, not_null in connection.execute(TABLES_SQL):
        tenant: TenantColumn = (
            "absent" if not_null is None else "not_null" if not_null else "nullable"
        )
        tables.append(
            Table(schema, name, tenant, rls, force, tuple(policies.get((schema, name), [])))
        )
    return tables


def read_catalog(dsn: str) -> list[Table]:
    # Imported here so that static mode needs no database driver.
    import psycopg

    with psycopg.connect(libpq_dsn(dsn)) as connection:
        return read_tables(connection)


def exemption_report(tables: Sequence[Table], config: LintConfig) -> list[str]:
    lines: list[str] = []
    for exemption in config.exemptions:
        count = sum(1 for table in tables if exemption.matches(table.qualified))
        noun = "table" if count == 1 else "tables"
        lines.append(f"  {exemption.kind} {exemption.table} ({count} {noun}): {exemption.reason}")
    return lines


# ------------------------------------------------------------------------------------------ CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    modes = parser.add_subparsers(dest="mode", required=True)
    static = modes.add_parser("static", help="migration files, no database")
    static.add_argument("--root", type=Path, default=ROOT, help="repository root")
    catalog = modes.add_parser("catalog", help="the catalog of a migrated database")
    catalog.add_argument("--dsn", required=True, help="postgresql://user:password@host:port/db")
    catalog.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args(argv)

    if args.mode == "static":
        total, problems = static_problems(args.root)
        for problem in problems:
            sys.stderr.write(f"migration lint: {problem}\n")
        if problems:
            return 1
        sys.stdout.write(
            f"migration lint: {total} migrations, one head per service, file names match "
            "revisions, downgrades present, contract steps marked\n"
        )
        return 0

    config = load_config(args.config)
    tables = read_catalog(args.dsn)
    problems = catalog_problems(tables, config)
    sys.stdout.write("migration lint: exemptions\n")
    for line in exemption_report(tables, config):
        sys.stdout.write(f"{line}\n")
    for problem in problems:
        sys.stderr.write(f"migration lint: {problem}\n")
    if problems:
        return 1
    schemas = len({table.schema for table in tables})
    sys.stdout.write(
        f"migration lint: {len(tables)} tables in {schemas} schemas; every tenant table has "
        "forced row-level security with the tenant policy\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
