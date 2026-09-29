"""Every event topic in code has a schema (guide section 7: an event is a versioned contract).

An AST scan of ``services/*/src`` and ``packages/*/src``, importing nothing, finds the classes
that set ``topic: ClassVar[str]``. Each topic needs ``events/schemas/<topic>.v<major>.json``
whose ``x-version`` equals the class's ``schema_version``, read from the class or, when it does
not set one, from the nearest base class that does (``DomainEvent`` says ``1.0.0``).

A topic that is still only a log line is listed in ``LOG_ONLY_TOPICS`` with the reason. An
entry is stale, and fails, once its topic has a schema file or no class declares it any more.

Usage, from the repo root (``make contracts-check`` runs it)::

    uv run python packages/contracts/scripts/check_topics.py
    uv run python packages/contracts/scripts/check_topics.py --root <repo> --schemas <dir>

Exit status 1 with one line per finding.
"""

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCHEMAS = REPO / "packages" / "contracts" / "events" / "schemas"
SOURCE_GLOBS = ("services/*/src/**/*.py", "packages/*/src/**/*.py")

LOG_ONLY_TOPICS: dict[str, str] = {
    "llm.call.completed": (
        "the gateway writes it to a log publisher until the Kafka outbox carries it and a"
        " consumer needs it"
    ),
    "llm.budget.alarmed": (
        "the gateway writes it to a log publisher until the Kafka outbox carries it and a"
        " consumer needs it"
    ),
}


@dataclass(frozen=True, slots=True)
class EventClass:
    name: str
    module: Path
    line: int
    bases: tuple[str, ...]
    topic: str | None
    schema_version: str | None

    @property
    def where(self) -> str:
        return f"{self.name} ({self.module}:{self.line})"


def class_var(node: ast.ClassDef, name: str) -> str | None:
    """The string a class body assigns to ``name: ClassVar[str]``, or None."""
    for statement in node.body:
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
            and "ClassVar" in ast.unparse(statement.annotation)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            return statement.value.value
    return None


def base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def scan(root: Path) -> list[EventClass]:
    """Every class under the source globs, with the topic and version it sets itself."""
    found: list[EventClass] = []
    for pattern in SOURCE_GLOBS:
        for path in sorted(root.glob(pattern)):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    found.append(
                        EventClass(
                            name=node.name,
                            module=path.relative_to(root),
                            line=node.lineno,
                            bases=tuple(base_name(base) for base in node.bases),
                            topic=class_var(node, "topic"),
                            schema_version=class_var(node, "schema_version"),
                        )
                    )
    return found


def version_of(event: EventClass, classes: list[EventClass]) -> str | None:
    """``schema_version`` from the class, else from its bases: same module first, then a unique
    name elsewhere."""
    seen: set[tuple[Path, str]] = set()
    pending = [event]
    while pending:
        current = pending.pop(0)
        if (current.module, current.name) in seen:
            continue
        seen.add((current.module, current.name))
        if current.schema_version is not None:
            return current.schema_version
        for name in current.bases:
            local = [c for c in classes if c.name == name and c.module == current.module]
            named = [c for c in classes if c.name == name]
            pending.extend(local or (named if len(named) == 1 else []))
    return None


def problems(classes: list[EventClass], schemas: Path, log_only: dict[str, str]) -> list[str]:
    events = [event for event in classes if event.topic]
    found: list[str] = []
    for event in events:
        topic = str(event.topic)
        if topic in log_only:
            continue
        version = version_of(event, classes)
        if version is None:
            found.append(f"{event.where}: topic {topic} but no schema_version on it or its bases")
            continue
        schema = schemas / f"{topic}.v{version.split('.')[0]}.json"
        if not schema.is_file():
            found.append(
                f"{event.where}: topic {topic} has no schema {schema.name}; write it with an"
                " example and a CHANGELOG line, then run make contracts"
            )
            continue
        declared = json.loads(schema.read_text(encoding="utf-8")).get("x-version")
        if declared != version:
            found.append(
                f"{event.where}: schema_version is {version} but {schema.name} has x-version"
                f" {declared}"
            )
    declared_topics = {event.topic for event in events}
    for topic in sorted(log_only):
        if any(schemas.glob(f"{topic}.v*.json")):
            found.append(f"LOG_ONLY_TOPICS: {topic} has a schema now; remove the entry")
        elif topic not in declared_topics:
            found.append(f"LOG_ONLY_TOPICS: no class declares {topic} any more; remove the entry")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=REPO, help="the repository to scan")
    parser.add_argument("--schemas", type=Path, default=SCHEMAS, help="the event schemas")
    args = parser.parse_args(argv)
    classes = scan(args.root)
    found = problems(classes, args.schemas, LOG_ONLY_TOPICS)
    for problem in found:
        sys.stderr.write(f"event topics: {problem}\n")
    if found:
        return 1
    topics = sorted({str(event.topic) for event in classes if event.topic})
    schema_backed = [topic for topic in topics if topic not in LOG_ONLY_TOPICS]
    sys.stdout.write(
        f"event topics: {len(schema_backed)} in code have a schema,"
        f" {len(topics) - len(schema_backed)} are log only\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
