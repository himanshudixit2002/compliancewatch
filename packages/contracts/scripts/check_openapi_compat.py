"""Backward compatibility of the committed OpenAPI specs against a base revision.

A change is backward compatible when every request a client built against the base still
succeeds and every response still carries what that client reads. After resolving ``$ref`` the
check fails on:

- a removed path or operation;
- a removed 2xx response, or a media type or property removed from one;
- a request body, body property or parameter that became required;
- a narrowed enum in a request: a value the base accepted is refused;
- a type change: a request that refuses a type the base accepted, or a response that may carry a
  type the base never returned.

Specs that are new on the branch are skipped, since no client depends on them yet. A deliberate
break needs a row in ``openapi/BREAKING.md`` added on the branch (spec, operation, reason, ADR).
Rows already on the base recorded earlier breaks and allow nothing new, and a new row that
matches no break fails, so the file cannot approve a break in advance.

Usage, from the repo root::

    uv run python packages/contracts/scripts/check_openapi_compat.py --base-ref origin/main
    uv run python packages/contracts/scripts/check_openapi_compat.py --base-dir A --head-dir B

Standard library only. Exit status 1 with one line per finding.
"""

import argparse
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
OPENAPI_DIR = Path("packages/contracts/openapi")
BREAKING = "BREAKING.md"
METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
SPEC_NAME = re.compile(r"[a-z0-9][a-z0-9-]*\.v[0-9]+\.json")
OPERATION = re.compile(r"(GET|PUT|POST|DELETE|OPTIONS|HEAD|PATCH|TRACE) (/\S*)")
ADR = re.compile(r"ADR-[0-9]{3}")
MAX_REF_DEPTH = 32

Schema = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Finding:
    spec: str
    operation: str
    message: str

    def __str__(self) -> str:
        return f"{self.spec} {self.operation}: {self.message}"


@dataclass(frozen=True, slots=True)
class Row:
    spec: str
    operation: str


def load(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SystemExit(f"{path}: not a JSON object")
    return document


def specs(directory: Path) -> dict[str, dict[str, Any]]:
    """The OpenAPI documents in a directory, by file name; other JSON files are ignored."""
    if not directory.is_dir():
        return {}
    documents = {path.name: load(path) for path in sorted(directory.glob("*.json"))}
    return {
        name: document
        for name, document in documents.items()
        if SPEC_NAME.fullmatch(name) and "openapi" in document
    }


def resolve(document: Mapping[str, Any], node: Any) -> tuple[Schema, str | None]:
    """Follow local ``$ref`` chains. Sibling keys of a ``$ref`` (a description) are kept."""
    first_ref: str | None = None
    for _ in range(MAX_REF_DEPTH):
        if not isinstance(node, Mapping):
            return {}, first_ref
        ref = node.get("$ref")
        if not isinstance(ref, str):
            return node, first_ref
        if not ref.startswith("#/"):
            raise SystemExit(f"only local $ref is supported, got {ref}")
        first_ref = first_ref or ref
        target: Any = document
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            target = target.get(part, {}) if isinstance(target, Mapping) else {}
        siblings = {key: value for key, value in node.items() if key != "$ref"}
        node = {**target, **siblings} if isinstance(target, Mapping) else siblings
    raise SystemExit(f"$ref chain deeper than {MAX_REF_DEPTH} at {first_ref}")


def branches(document: Mapping[str, Any], schema: Schema) -> list[Schema]:
    """The alternatives of a schema: its ``anyOf`` or ``oneOf`` branches, flattened, or itself."""
    alternatives = schema.get("anyOf") or schema.get("oneOf")
    if not alternatives:
        return [schema]
    flat: list[Schema] = []
    for branch in alternatives:
        resolved, _ = resolve(document, branch)
        flat.extend(branches(document, resolved))
    return flat


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "array" if isinstance(value, list) else "object"


def types_of(document: Mapping[str, Any], schema: Schema) -> frozenset[str] | None:
    """The JSON types a schema admits, or None when it does not constrain the type."""
    found: set[str] = set()
    for branch in branches(document, schema):
        declared = branch.get("type")
        if isinstance(declared, str):
            found.add(declared)
        elif isinstance(declared, list):
            found.update(str(item) for item in declared)
        elif "enum" in branch:
            found.update(json_type(value) for value in branch["enum"])
        elif "const" in branch:
            found.add(json_type(branch["const"]))
        elif "properties" in branch:
            found.add("object")
        elif "items" in branch:
            found.add("array")
        elif "allOf" in branch:
            inner = [types_of(document, resolve(document, part)[0]) for part in branch["allOf"]]
            known = [types for types in inner if types is not None]
            if not known:
                return None
            found.update(frozenset.intersection(*known))
        else:
            return None
    return frozenset(found)


def covers(wide: frozenset[str], narrow: frozenset[str]) -> bool:
    """Every type in ``narrow`` is admitted by ``wide`` (an integer is also a number)."""
    return all(kind in wide or (kind == "integer" and "number" in wide) for kind in narrow)


def enum_of(document: Mapping[str, Any], schema: Schema) -> set[str] | None:
    """The values a schema admits as JSON text, or None when it is not an enum."""
    values: set[str] = set()
    for branch in branches(document, schema):
        if "enum" in branch:
            values.update(json.dumps(value, sort_keys=True) for value in branch["enum"])
        elif "const" in branch:
            values.add(json.dumps(branch["const"], sort_keys=True))
        elif branch.get("type") == "null":
            values.add("null")
        else:
            return None
    return values


def object_view(document: Mapping[str, Any], schema: Schema) -> tuple[dict[str, Any], set[str]]:
    """Properties and required names across a schema's alternatives and ``allOf`` parts."""
    properties: dict[str, Any] = {}
    required: set[str] = set()
    for branch in branches(document, schema):
        parts = [branch, *(resolve(document, part)[0] for part in branch.get("allOf", []))]
        for part in parts:
            properties.update(part.get("properties") or {})
            required.update(part.get("required") or [])
    return properties, required


def items_of(document: Mapping[str, Any], schema: Schema) -> Any:
    for branch in branches(document, schema):
        if "items" in branch:
            return branch["items"]
    return None


@dataclass
class Comparison:
    """Compares one operation of a base spec with the same operation of the head spec."""

    base_doc: Mapping[str, Any]
    head_doc: Mapping[str, Any]
    spec: str
    operation: str
    findings: list[Finding] = field(default_factory=list)
    _seen: set[tuple[str, str, str]] = field(default_factory=set)

    def report(self, message: str) -> None:
        self.findings.append(Finding(self.spec, self.operation, message))

    def schema(self, base_node: Any, head_node: Any, where: str, *, request: bool) -> None:
        base, base_ref = resolve(self.base_doc, base_node)
        head, head_ref = resolve(self.head_doc, head_node)
        if base_ref and head_ref:
            key = (base_ref, head_ref, "request" if request else "response")
            if key in self._seen:
                return
            self._seen.add(key)
        self._types(base, head, where, request=request)
        if request:
            self._enum(base, head, where)
        base_props, base_required = object_view(self.base_doc, base)
        head_props, head_required = object_view(self.head_doc, head)
        if request:
            for name in sorted(head_required - base_required):
                self.report(f"{where}.{name} became required")
        else:
            for name in sorted(set(base_props) - set(head_props)):
                self.report(f"{where}.{name} removed")
        for name in sorted(set(base_props) & set(head_props)):
            self.schema(base_props[name], head_props[name], f"{where}.{name}", request=request)
        base_items, head_items = items_of(self.base_doc, base), items_of(self.head_doc, head)
        if base_items is not None and head_items is not None:
            self.schema(base_items, head_items, f"{where}[]", request=request)

    def _types(self, base: Schema, head: Schema, where: str, *, request: bool) -> None:
        base_types, head_types = types_of(self.base_doc, base), types_of(self.head_doc, head)
        if request:
            # A request must still accept every type the base accepted.
            if head_types is None or (base_types is not None and covers(head_types, base_types)):
                return
        # A response must not return a type the base never returned.
        elif base_types is None or (head_types is not None and covers(base_types, head_types)):
            return
        self.report(f"{where} type changed from {describe(base_types)} to {describe(head_types)}")

    def _enum(self, base: Schema, head: Schema, where: str) -> None:
        head_values = enum_of(self.head_doc, head)
        if head_values is None:
            return
        base_values = enum_of(self.base_doc, base)
        if base_values is None:
            self.report(f"{where} now accepts only {', '.join(sorted(head_values))}")
            return
        refused = sorted(base_values - head_values)
        if refused:
            self.report(f"{where} no longer accepts {', '.join(refused)}")


def describe(types: frozenset[str] | None) -> str:
    return "any" if types is None else "|".join(sorted(types)) or "nothing"


def operations(document: Mapping[str, Any]) -> Iterator[tuple[str, str, Schema, Schema]]:
    """``(label, path, path item, operation)`` for every operation of a spec."""
    for path, raw_item in (document.get("paths") or {}).items():
        item, _ = resolve(document, raw_item)
        for method in METHODS:
            if method in item:
                operation, _ = resolve(document, item[method])
                yield f"{method.upper()} {path}", path, item, operation


def parameters(document: Mapping[str, Any], item: Schema, operation: Schema) -> dict[str, Schema]:
    """Parameters by ``<in> parameter <name>``; header names compare case-insensitively."""
    found: dict[str, Schema] = {}
    for raw in [*(item.get("parameters") or []), *(operation.get("parameters") or [])]:
        parameter, _ = resolve(document, raw)
        location, name = parameter.get("in", ""), str(parameter.get("name", ""))
        found[f"{location} parameter {name.lower() if location == 'header' else name}"] = parameter
    return found


def compare_operation(
    comparison: Comparison, base: tuple[Schema, Schema], head: tuple[Schema, Schema]
) -> None:
    """Parameters, request body and 2xx responses of one operation; each argument is
    ``(path item, operation)``."""
    base_doc, head_doc = comparison.base_doc, comparison.head_doc
    base_params = parameters(base_doc, *base)
    for key, parameter in parameters(head_doc, *head).items():
        before = base_params.get(key)
        if parameter.get("required") and not (before and before.get("required")):
            comparison.report(f"{key} became required")
        if before is not None:
            comparison.schema(before.get("schema"), parameter.get("schema"), key, request=True)
    base_op, head_op = base[1], head[1]
    base_body, _ = resolve(base_doc, base_op.get("requestBody"))
    head_body, _ = resolve(head_doc, head_op.get("requestBody"))
    if head_body.get("required") and not base_body.get("required"):
        comparison.report("request body became required")
    if head_body:
        accepted = head_body.get("content") or {}
        for media, base_media in (base_body.get("content") or {}).items():
            if media not in accepted:
                comparison.report(f"request body no longer accepts {media}")
                continue
            comparison.schema(
                base_media.get("schema"),
                accepted[media].get("schema"),
                "request body",
                request=True,
            )
    head_responses = head_op.get("responses") or {}
    for code, raw_response in (base_op.get("responses") or {}).items():
        if not str(code).startswith("2"):
            continue
        if code not in head_responses:
            comparison.report(f"response {code} removed")
            continue
        base_response, _ = resolve(base_doc, raw_response)
        head_response, _ = resolve(head_doc, head_responses[code])
        returned = head_response.get("content") or {}
        for media, base_media in (base_response.get("content") or {}).items():
            if media not in returned:
                comparison.report(f"response {code} no longer returns {media}")
                continue
            comparison.schema(
                base_media.get("schema"),
                returned[media].get("schema"),
                f"response {code} body",
                request=False,
            )


def check(base: Path, head: Path) -> list[Finding]:
    """Every break between the base and head spec directories, allowed or not."""
    findings: list[Finding] = []
    head_specs = specs(head)
    for name, base_doc in specs(base).items():
        head_doc = head_specs.get(name, {"paths": {}})
        head_ops = {label: (item, operation) for label, _, item, operation in operations(head_doc)}
        head_paths = set((head_doc.get("paths") or {}).keys())
        for label, path, item, operation in operations(base_doc):
            comparison = Comparison(base_doc, head_doc, name, label)
            if path not in head_paths:
                comparison.report("path removed")
            elif label not in head_ops:
                comparison.report("operation removed")
            else:
                compare_operation(comparison, (item, operation), head_ops[label])
            findings.extend(comparison.findings)
    return findings


def breaking_rows(path: Path) -> tuple[set[Row], list[str]]:
    """The rows of a BREAKING.md table, and a problem per malformed row."""
    if not path.is_file():
        return set(), []
    rows: set[Row] = set()
    problems: list[str] = []
    fenced = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if fenced or not line.startswith("|"):
            continue
        cells = [cell.strip().strip("`").strip() for cell in line.strip().strip("|").split("|")]
        if cells[0].lower() == "spec" or set("".join(cells)) <= set("-: "):
            continue
        if len(cells) != 4:
            problems.append(f"{path.name}:{number}: expected | spec | operation | reason | ADR |")
            continue
        spec, operation, reason, adr = cells
        if not SPEC_NAME.fullmatch(spec):
            problems.append(f"{path.name}:{number}: {spec!r} is not a spec file name")
        elif not OPERATION.fullmatch(operation):
            problems.append(f"{path.name}:{number}: {operation!r} is not METHOD /path")
        elif not reason or not ADR.search(adr):
            problems.append(f"{path.name}:{number}: a break needs a reason and an ADR-NNN")
        else:
            rows.add(Row(spec, operation))
    return rows, problems


def extract_base(ref: str) -> Path:
    """The base revision's openapi directory, extracted with ``git archive`` into a temp dir."""
    target = Path(tempfile.mkdtemp(prefix="cw-openapi-base-"))
    result = subprocess.run(
        ["git", "archive", "--format=tar", ref, str(OPENAPI_DIR)],
        cwd=REPO,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        if "did not match any files" in message:
            return target / OPENAPI_DIR
        raise SystemExit(f"git archive {ref} failed: {message}")
    with tarfile.open(fileobj=BytesIO(result.stdout)) as archive:
        archive.extractall(target, filter="data")
    return target / OPENAPI_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-ref", default="origin/main", help="git ref of the base revision")
    parser.add_argument(
        "--base-dir", type=Path, help="openapi directory of the base (instead of --base-ref)"
    )
    parser.add_argument("--head-dir", type=Path, default=REPO / OPENAPI_DIR)
    args = parser.parse_args(argv)
    base = args.base_dir if args.base_dir is not None else extract_base(args.base_ref)
    head: Path = args.head_dir
    findings = check(base, head)
    base_rows, _ = breaking_rows(base / BREAKING)
    head_rows, problems = breaking_rows(head / BREAKING)
    new_rows = head_rows - base_rows
    allowed = [f for f in findings if Row(f.spec, f.operation) in new_rows]
    breaking = [f for f in findings if Row(f.spec, f.operation) not in new_rows]
    used = {Row(f.spec, f.operation) for f in allowed}
    for row in sorted(new_rows - used, key=lambda row: (row.spec, row.operation)):
        problems.append(f"{BREAKING}: {row.spec} {row.operation} matches no breaking change")
    for finding in allowed:
        sys.stdout.write(f"allowed by {BREAKING}: {finding}\n")
    for finding in breaking:
        sys.stderr.write(f"breaking: {finding}\n")
    for problem in problems:
        sys.stderr.write(f"error: {problem}\n")
    if breaking:
        sys.stderr.write(
            f"a deliberate break needs a row in {OPENAPI_DIR / BREAKING} with its reason and ADR\n"
        )
    if breaking or problems:
        return 1
    compared = sorted(set(specs(base)) & set(specs(head)))
    sys.stdout.write(
        f"openapi specs are backward compatible with {args.base_dir or args.base_ref}"
        f" ({len(compared)} compared: {', '.join(compared) or 'none'})\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
