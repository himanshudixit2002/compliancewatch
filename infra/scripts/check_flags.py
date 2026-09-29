"""The feature flag registry is well formed and names every switch in the code.

``packages/flags/registry.json`` lists every rollout switch with its owner, default, expiry date
and removal condition (guide section 17: flags default off). This check:

- validates the registry against ``registry.schema.json`` (JSON Schema 2020-12);
- requires unique names in sorted order, each environment variable read by one flag, a false
  default for every bool flag, a string flag's default among its values, services that exist and an
  ``expires`` date that has not passed;
- compares ``packages/py-common/src/py_common/flags_registry.json``, the copy py-common loads,
  with the registry (``write`` regenerates it first: ``make flags``);
- reads every settings module (py-common's, ``services/*/src/*/settings.py`` and
  ``composition/*/src/*/settings.py``) and classifies each bool and ``Literal`` field.

A field is a flag when it is a bool named ``*_enabled``, when its name ends in ``_provider``,
``_mode`` or ``_backend``, or when it is listed in ``SWITCH_FIELDS``. A flag needs a registry
entry whose ``env`` is the field's variable, with the same type, default and values. Every other
bool or ``Literal`` field is configuration and must be listed in ``NOT_FLAGS`` with the reason, so
a new switch cannot slip in unregistered. A field named ``*_tenants`` is a flag's tenant
allow-list and must be the ``tenants_env`` of an entry. Entries without a settings field are
allowed: the TypeScript apps and the flags read through the SDK have none.

The scan reads the modules' syntax and imports nothing, so a ``Literal`` alias must be declared in
the settings module that uses it. Exit code 1 lists the problems. Run as ``make flags-check``
(part of ``make check``) or ``make flags``.
"""

import argparse
import ast
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[2]
FLAGS_DIR = ROOT / "packages" / "flags"
REGISTRY = FLAGS_DIR / "registry.json"
SCHEMA = FLAGS_DIR / "registry.schema.json"
PY_COPY = ROOT / "packages" / "py-common" / "src" / "py_common" / "flags_registry.json"
SETTINGS_PATTERNS = (
    "packages/py-common/src/py_common/settings.py",
    "services/*/src/*/settings.py",
    "composition/*/src/*/settings.py",
)
# Where the directory names in an entry's services live.
COMPONENT_DIRS = ("services", "apps", "packages", "composition")
ENV_PREFIX = "CW_"
OVERRIDE_PREFIX = "CW_FLAG_"
TENANTS_SUFFIX = "__TENANTS"
FLAG_SUFFIXES = ("_provider", "_mode", "_backend")
COPY_NOTE = "Generated from packages/flags/registry.json by make flags; do not edit."

# Fields that are flags although their names do not say so.
SWITCH_FIELDS: frozenset[str] = frozenset(
    {
        "profile_gstin_lookup",  # the GSTIN lookup provider; http arrives behind it
    }
)

# Bool and Literal settings that are configuration, not rollout switches, each with the reason.
_STORE = "store selector: memory for tests and demos, postgres otherwise"
NOT_FLAGS: Mapping[str, str] = {
    "CW_ENV": "names the deployment environment, set once per environment",
    "CW_LOG_LEVEL": "log verbosity",
    "CW_LOG_JSON": "log format: JSON lines in deployments, console output locally",
    "CW_IDENTITY_STORE": _STORE,
    "CW_PROFILE_STORE": _STORE,
    "CW_RULEBOOK_STORE": _STORE,
    "CW_OBLIGATION_STORE": _STORE,
    "CW_NOTIFICATION_STORE": _STORE,
    "CW_LLM_LEDGER": "store selector of the gateway's usage ledger: memory or postgres",
    "CW_LLM_EMBEDDING_DIMENSIONS_PARAM": (
        "provider compatibility: whether an embedding request carries dimensions=512, for a "
        "model without that parameter; not a rollout, and it defaults on"
    ),
    "CW_AI_GATEWAY_ZERO_DATA_RETENTION": (
        "data protection on every provider request; it stays on, so it is not a rollout"
    ),
    "CW_LLM_ALLOW_UNREGISTERED_PROMPTS": (
        "an escape hatch from the prompt registry for local experiments, never set in a shared "
        "environment"
    ),
}


@dataclass(frozen=True)
class Setting:
    """One field of a settings class, as the scan sees it."""

    path: str
    class_name: str
    name: str
    kind: str  # bool, literal, tenants or other
    values: tuple[str, ...] = ()
    default: object = None
    has_default: bool = False

    @property
    def env(self) -> str:
        return ENV_PREFIX + self.name.upper()

    @property
    def where(self) -> str:
        return f"{self.path}: {self.class_name}.{self.name} ({self.env})"


def override_env(name: str) -> str:
    """The variable that sets a flag by its registry name in the env provider."""
    return OVERRIDE_PREFIX + name.upper().replace(".", "_")


def render_copy(registry: Any) -> str:
    """py-common's copy: the registry's entries under a note that the file is generated."""
    flags = registry.get("flags", []) if isinstance(registry, dict) else []
    body = {"_generated": COPY_NOTE, "flags": flags}
    return json.dumps(body, indent=2, ensure_ascii=False) + "\n"


def _entries(registry: Any) -> list[dict[str, Any]]:
    flags = registry.get("flags") if isinstance(registry, dict) else None
    if not isinstance(flags, list):
        return []
    return [entry for entry in flags if isinstance(entry, dict)]


def _label(entry: Mapping[str, Any]) -> str:
    name = entry.get("name")
    return name if isinstance(name, str) else "<unnamed flag>"


def _schema_problem(error: ValidationError, entries: Sequence[Any]) -> str:
    path = list(error.absolute_path)
    if len(path) >= 2 and path[0] == "flags" and isinstance(path[1], int):
        entry = entries[path[1]] if path[1] < len(entries) else None
        label = _label(entry) if isinstance(entry, dict) else f"flags[{path[1]}]"
        rest = "/".join(str(part) for part in path[2:])
        return f"{label}: {rest + ': ' if rest else ''}{error.message}"
    where = "/".join(str(part) for part in path) or "registry"
    return f"{where}: {error.message}"


def registry_problems(registry: Any, schema: Any, *, root: Path, today: date) -> list[str]:
    """Schema, names, variables, defaults, services and expiry dates of the registry."""
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    raw = registry.get("flags") if isinstance(registry, dict) else None
    listed = raw if isinstance(raw, list) else []
    found = [
        _schema_problem(error, listed)
        for error in sorted(validator.iter_errors(registry), key=lambda e: str(e.absolute_path))
        # A bool default that is not false gets its own, clearer message below.
        if not (error.validator == "const" and list(error.absolute_path)[-1:] == ["default"])
    ]
    entries = _entries(registry)
    names = [_label(entry) for entry in entries]
    for name in sorted({name for name in names if names.count(name) > 1}):
        found.append(f"{name}: registered {names.count(name)} times; names are unique")
    if names != sorted(names):
        found.append(
            "registry: flags are not sorted by name; keep them sorted so merges stay clean"
        )
    variables: dict[str, set[str]] = {}
    for entry in entries:
        name = _label(entry)
        found.extend(_entry_problems(entry, root=root, today=today))
        for key in ("env", "tenants_env"):
            if isinstance(entry.get(key), str):
                variables.setdefault(entry[key], set()).add(name)
        variables.setdefault(override_env(name), set()).add(name)
        variables.setdefault(override_env(name) + TENANTS_SUFFIX, set()).add(name)
    for variable, readers in sorted(variables.items()):
        if len(readers) > 1:
            found.append(f"{variable} is read by more than one flag: {', '.join(sorted(readers))}")
    return found


def _entry_problems(entry: Mapping[str, Any], *, root: Path, today: date) -> list[str]:
    name = _label(entry)
    found: list[str] = []
    default = entry.get("default")
    if entry.get("type") == "bool" and default is not False:
        found.append(f"{name}: a bool flag defaults to false (off), not {json.dumps(default)}")
    values = entry.get("values")
    if entry.get("type") == "string" and isinstance(values, list) and default not in values:
        found.append(f"{name}: default {json.dumps(default)} is not one of its values {values}")
    expires = entry.get("expires")
    try:
        expiry = date.fromisoformat(expires) if isinstance(expires, str) else None
    except ValueError:
        expiry = None  # the schema's date format reports it
    if expiry is not None and expiry < today:
        found.append(
            f"{name}: expired on {expires}; remove the flag ({entry.get('removal', 'no removal')}) "
            f"or have its owner, {entry.get('owner', 'unknown')}, extend expires"
        )
    services = entry.get("services")
    for service in services if isinstance(services, list) else []:
        if isinstance(service, str) and not any(
            (root / directory / service).is_dir() for directory in COMPONENT_DIRS
        ):
            found.append(
                f"{name}: service {service} is not a directory under "
                f"{', '.join(f'{directory}/' for directory in COMPONENT_DIRS)}"
            )
    return found


def copy_problems(registry: Any, copy_path: Path) -> list[str]:
    """py-common's copy exists and matches the registry."""
    shown = _shown(copy_path)
    if not copy_path.is_file():
        return [f"{shown} is missing; run make flags"]
    if copy_path.read_text(encoding="utf-8") != render_copy(registry):
        return [f"{shown} differs from packages/flags/registry.json; run make flags and commit it"]
    return []


def _shown(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


# ---------------------------------------------------------------- settings modules


def settings_fields(root: Path) -> list[Setting]:
    """Every field of every settings class under the scanned paths."""
    found: list[Setting] = []
    for pattern in SETTINGS_PATTERNS:
        for path in sorted(root.glob(pattern)):
            found.extend(module_settings(path, root))
    return found


def module_settings(path: Path, root: Path) -> list[Setting]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    aliases = _literal_aliases(tree)
    shown = path.relative_to(root).as_posix()
    found: list[Setting] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not any(
            _name_of(base).endswith("Settings") for base in node.bases
        ):
            continue
        for item in node.body:
            if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
                continue
            if item.target.id == "model_config" or _name_of(item.annotation) == "ClassVar":
                continue
            kind, values = _classify(item.annotation, aliases)
            if item.target.id.endswith("_tenants"):
                kind, values = "tenants", ()
            has_default, default = _default(item.value)
            found.append(
                Setting(shown, node.name, item.target.id, kind, values, default, has_default)
            )
    return found


def _name_of(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _name_of(node.value)
    return ""


def _literal_values(node: ast.expr) -> tuple[str, ...] | None:
    if not (isinstance(node, ast.Subscript) and _name_of(node.value) == "Literal"):
        return None
    items = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    return tuple(
        str(item.value) if isinstance(item, ast.Constant) else ast.unparse(item) for item in items
    )


def _literal_aliases(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    """Module-level ``Name = Literal[...]``, ``Name: TypeAlias = Literal[...]`` and
    ``type Name = Literal[...]``."""
    aliases: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.TypeAlias):
            target, value = node.name, node.value
        values = _literal_values(value) if value is not None else None
        if isinstance(target, ast.Name) and values is not None:
            aliases[target.id] = values
    return aliases


def _classify(
    annotation: ast.expr, aliases: Mapping[str, tuple[str, ...]]
) -> tuple[str, tuple[str, ...]]:
    """bool, literal (with its values) or other, looking through ``X | None``, ``Optional``
    and ``Annotated``."""
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        parts = [
            part
            for part in (annotation.left, annotation.right)
            if not (isinstance(part, ast.Constant) and part.value is None)
        ]
        return _classify(parts[0], aliases) if len(parts) == 1 else ("other", ())
    if isinstance(annotation, ast.Subscript) and _name_of(annotation.value) == "Optional":
        return _classify(annotation.slice, aliases)
    if isinstance(annotation, ast.Subscript) and _name_of(annotation.value) == "Annotated":
        inner = annotation.slice
        return _classify(inner.elts[0] if isinstance(inner, ast.Tuple) else inner, aliases)
    if isinstance(annotation, ast.Name) and annotation.id == "bool":
        return "bool", ()
    values = _literal_values(annotation)
    if values is not None:
        return "literal", values
    if isinstance(annotation, ast.Name) and annotation.id in aliases:
        return "literal", aliases[annotation.id]
    return "other", ()


def _default(value: ast.expr | None) -> tuple[bool, object]:
    """The field's default when it is a constant, directly or as ``Field(default=...)``."""
    if isinstance(value, ast.Constant):
        return True, value.value
    if isinstance(value, ast.Call) and _name_of(value.func) == "Field":
        for keyword in value.keywords:
            if keyword.arg == "default" and isinstance(keyword.value, ast.Constant):
                return True, keyword.value.value
        if value.args and isinstance(value.args[0], ast.Constant):
            return True, value.args[0].value
    return False, None


def is_flag(setting: Setting, switch_fields: frozenset[str] = SWITCH_FIELDS) -> bool:
    return (
        (setting.kind == "bool" and setting.name.endswith("_enabled"))
        or setting.name.endswith(FLAG_SUFFIXES)
        or setting.name in switch_fields
    )


def scan_problems(
    registry: Any,
    settings: Sequence[Setting],
    *,
    not_flags: Mapping[str, str] = NOT_FLAGS,
    switch_fields: frozenset[str] = SWITCH_FIELDS,
) -> list[str]:
    """Every flag in the settings is registered and every other switch-shaped field is listed
    as configuration."""
    entries = _entries(registry)
    by_env = {entry["env"]: entry for entry in entries if isinstance(entry.get("env"), str)}
    allow_lists = {entry["tenants_env"] for entry in entries if "tenants_env" in entry}
    found: list[str] = []
    for setting in settings:
        if setting.kind == "tenants":
            if setting.env not in allow_lists:
                found.append(
                    f"{setting.where}: a tenant allow-list that no registry entry names as its "
                    "tenants_env"
                )
            continue
        flag = is_flag(setting, switch_fields)
        if flag and setting.env in not_flags:
            found.append(
                f"{setting.where}: is a flag by its name, so NOT_FLAGS cannot exempt it; "
                "register it instead"
            )
        entry = by_env.get(setting.env)
        if entry is not None:
            found.extend(_matches(setting, entry))
        elif flag:
            found.append(
                f"{setting.where}: is a flag, but packages/flags/registry.json has no entry with "
                f'"env": "{setting.env}"; register it (make flags)'
            )
        elif setting.kind in ("bool", "literal") and setting.env not in not_flags:
            found.append(
                f"{setting.where}: a {setting.kind} setting that is neither a registered flag nor "
                "listed in NOT_FLAGS (infra/scripts/check_flags.py); name a bool switch *_enabled "
                "and register it, or list the setting in NOT_FLAGS with the reason it is "
                "configuration"
            )
    declared = {setting.env for setting in settings}
    for variable, reason in sorted(not_flags.items()):
        if variable not in declared:
            found.append(f"NOT_FLAGS lists {variable}, which no settings module declares")
        if not reason.strip():
            found.append(f"NOT_FLAGS lists {variable} without a reason")
    return found


def _matches(setting: Setting, entry: Mapping[str, Any]) -> list[str]:
    name = _label(entry)
    if setting.kind not in ("bool", "literal"):
        return [f"{setting.where}: registered as {name}, but a flag is a bool or a Literal"]
    expected = "bool" if setting.kind == "bool" else "string"
    if entry.get("type") != expected:
        return [
            f"{setting.where}: a {setting.kind} setting, but {name} has type {entry.get('type')}"
        ]
    found: list[str] = []
    if not setting.has_default:
        found.append(f"{setting.where}: has no constant default; a flag is off unless set")
    elif setting.default != entry.get("default") or type(setting.default) is not type(
        entry.get("default")
    ):
        found.append(
            f"{setting.where}: defaults to {setting.default!r}, but {name} defaults to "
            f"{json.dumps(entry.get('default'))}"
        )
    values = entry.get("values")
    if setting.kind == "literal" and set(setting.values) != set(
        values if isinstance(values, list) else []
    ):
        found.append(f"{setting.where}: takes {list(setting.values)}, but {name} lists {values}")
    return found


# ---------------------------------------------------------------- entry point


def problems(
    *,
    registry_path: Path | None = None,
    schema_path: Path | None = None,
    copy_path: Path | None = None,
    root: Path | None = None,
    today: date | None = None,
) -> list[str]:
    """Everything this check reports, for the repository or for the paths given."""
    registry_path = registry_path or REGISTRY
    root = root or ROOT
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        schema = json.loads((schema_path or SCHEMA).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"cannot read the registry or its schema: {error}"]
    return [
        *registry_problems(registry, schema, root=root, today=today or date.today()),
        *copy_problems(registry, copy_path or PY_COPY),
        *scan_problems(registry, settings_fields(root)),
    ]


def write_copy(registry_path: Path | None = None, copy_path: Path | None = None) -> Path:
    """Regenerate py-common's copy from the registry (``make flags``)."""
    registry = json.loads((registry_path or REGISTRY).read_text(encoding="utf-8"))
    target = copy_path or PY_COPY
    target.write_text(render_copy(registry), encoding="utf-8")
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("check", "write"),
        default="check",
        help="check (make flags-check) or write py-common's copy, then check (make flags)",
    )
    args = parser.parse_args(argv)
    if args.command == "write":
        try:
            written = write_copy()
        except (OSError, json.JSONDecodeError) as error:
            sys.stderr.write(f"flags: cannot read the registry: {error}\n")
            return 1
        sys.stdout.write(f"flags: wrote {_shown(written)}\n")
    found = problems()
    for problem in found:
        sys.stderr.write(f"flags check: {problem}\n")
    if found:
        return 1
    count = len(_entries(json.loads(REGISTRY.read_text(encoding="utf-8"))))
    sys.stdout.write(
        f"flags check: {count} flags registered; every switch in the settings modules is "
        "registered or listed as configuration\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
