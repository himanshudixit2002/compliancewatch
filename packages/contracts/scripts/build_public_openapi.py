"""Build the public API spec, ``openapi/public.v1.json``, from the committed service specs.

A service puts an operation in the public API by tagging it ``public``. This script reads every
``openapi/<service>.v1.json``, keeps those operations, and writes one spec for clients of the
public API (guide section 10):

- each operation keeps what its service documents and gains ``x-service``, the service that
  serves it, so the gateway and the combined app can route by path;
- the same path and method in two services, or the same ``operationId`` twice, fails;
- only the components the kept operations reach are copied. Identical components are shared;
  a name two services use for different content is prefixed with each service's name in
  PascalCase (``Problem`` becomes ``ProfileProblem``) and every reference follows the rename;
- ``info`` comes from ``openapi/public.meta.json``, and the ``bearerAuth`` security scheme is
  added and required on every operation.

The public operations must follow the API rules, and the build fails with one line per
operation that does not:

- ``x-roles`` names one or more of the tenant roles in ``ROLES``;
- every documented 4xx or 5xx response is a problem document (``application/problem+json``),
  and there is at least one;
- a POST that answers 201 declares the ``Idempotency-Key`` header as required, since the
  services refuse such a request without it (428);
- a GET that answers a page (``items`` and ``next_cursor``) declares the ``limit`` and
  ``cursor`` query parameters.

``openapi/CHANGELOG.md`` must have a section for the version in ``public.meta.json``.

Usage, from the repo root::

    uv run python packages/contracts/scripts/build_public_openapi.py          # make openapi-public
    uv run python packages/contracts/scripts/build_public_openapi.py --check  # exit 1 when stale

Standard library only. Exit status 1 with one line per problem.
"""

import argparse
import json
import re
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
OPENAPI_DIR = REPO / "packages" / "contracts" / "openapi"
PUBLIC = "public.v1.json"
META = "public.meta.json"
CHANGELOG = "CHANGELOG.md"
PUBLIC_TAG = "public"
SERVICE_SPEC = re.compile(r"(?P<service>[a-z0-9][a-z0-9-]*)\.v1\.json")
SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
PROBLEM_MEDIA = "application/problem+json"
# The tenant roles an operation may name in x-roles. The identity service will own the role list;
# until then this follows the tenant-member roles the profile service declares.
ROLES = ("owner", "staff", "ca_admin", "ca_staff", "compliance_lead")
SECURITY_SCHEME = "bearerAuth"
BEARER_AUTH = {
    "type": "http",
    "scheme": "bearer",
    "bearerFormat": "JWT",
    "description": (
        "An access token from the identity service. Until it issues tokens, the services take the"
        " tenant from the x-tenant-id header."
    ),
}
REF_PREFIX = "#/components/"

Ref = tuple[str, str]
"""A component by kind and name: ``("schemas", "Problem")``."""


class BuildError(Exception):
    """The public spec cannot be built; ``problems`` has one line each."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


def load(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise BuildError([f"{path.name}: not a JSON object"])
    return document


def service_specs(directory: Path) -> dict[str, dict[str, Any]]:
    """The committed service specs by service name; the public spec itself is not one."""
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.v1.json")):
        match = SERVICE_SPEC.fullmatch(path.name)
        if match is None or path.name == PUBLIC:
            continue
        document = load(path)
        if "openapi" in document:
            found[match.group("service")] = document
    return found


def pascal(service: str) -> str:
    return "".join(part.capitalize() for part in service.split("-"))


def parse_ref(ref: str) -> Ref:
    if not ref.startswith(REF_PREFIX):
        raise BuildError([f"only local component references are supported, got {ref}"])
    kind, _, name = ref.removeprefix(REF_PREFIX).partition("/")
    if not kind or not name or "/" in name:
        raise BuildError([f"not a component reference: {ref}"])
    return kind, name.replace("~1", "/").replace("~0", "~")


def refs_in(node: Any) -> Iterator[Ref]:
    """Every component a JSON value references, at any depth."""
    if isinstance(node, Mapping):
        ref = node.get("$ref")
        if isinstance(ref, str):
            yield parse_ref(ref)
        for value in node.values():
            yield from refs_in(value)
    elif isinstance(node, list):
        for value in node:
            yield from refs_in(value)


def component(spec: Mapping[str, Any], ref: Ref) -> Any:
    kind, name = ref
    found = (spec.get("components") or {}).get(kind, {}).get(name)
    if found is None:
        raise BuildError([f"#/components/{kind}/{name} is referenced but not defined"])
    return found


def reachable(spec: Mapping[str, Any], roots: list[Any]) -> set[Ref]:
    """The components the given operations reach, directly or through other components."""
    seen: set[Ref] = set()
    pending = [ref for root in roots for ref in refs_in(root)]
    while pending:
        ref = pending.pop()
        if ref in seen:
            continue
        seen.add(ref)
        pending.extend(refs_in(component(spec, ref)))
    return seen


def rewrite(node: Any, names: Mapping[Ref, str]) -> Any:
    """A copy of ``node`` with every component reference following ``names``."""
    if isinstance(node, Mapping):
        copied = {key: rewrite(value, names) for key, value in node.items()}
        ref = node.get("$ref")
        if isinstance(ref, str):
            kind, name = parse_ref(ref)
            copied["$ref"] = f"{REF_PREFIX}{kind}/{names.get((kind, name), name)}"
        return copied
    if isinstance(node, list):
        return [rewrite(value, names) for value in node]
    return node


def canonical(node: Any) -> str:
    return json.dumps(node, sort_keys=True, separators=(",", ":"))


def public_operations(service: str, spec: Mapping[str, Any]) -> list[tuple[str, str, Any]]:
    """``(path, method, operation)`` for each operation of a service tagged public."""
    kept: list[tuple[str, str, Any]] = []
    for path, item in sorted((spec.get("paths") or {}).items()):
        for method in METHODS:
            operation = item.get(method)
            if isinstance(operation, Mapping) and PUBLIC_TAG in (operation.get("tags") or []):
                extra = sorted(set(item) - set(METHODS))
                if extra:
                    raise BuildError(
                        [f"{service} {path}: path-level {', '.join(extra)} is not supported"]
                    )
                kept.append((path, method, operation))
    return kept


def component_names(
    specs: Mapping[str, Mapping[str, Any]], used: Mapping[str, set[Ref]]
) -> dict[str, dict[Ref, str]]:
    """The name each service's components get in the public spec.

    A name whose content differs between services is prefixed in every service that uses it.
    A rename changes the references inside other components, which can make two copies of
    another name differ, so the grouping repeats until no new name needs a prefix.
    """
    names: dict[str, dict[Ref, str]] = {
        service: {ref: ref[1] for ref in refs} for service, refs in used.items()
    }
    while True:
        variants: dict[Ref, set[str]] = {}
        for service, refs in used.items():
            for ref in refs:
                if names[service][ref] == ref[1]:
                    content = rewrite(component(specs[service], ref), names[service])
                    variants.setdefault(ref, set()).add(canonical(content))
        clashing = sorted(ref for ref, contents in variants.items() if len(contents) > 1)
        if not clashing:
            return names
        for ref in clashing:
            for service, refs in used.items():
                if ref in refs:
                    names[service][ref] = f"{pascal(service)}{ref[1]}"


def merged_components(
    specs: Mapping[str, Mapping[str, Any]],
    used: Mapping[str, set[Ref]],
    names: Mapping[str, Mapping[Ref, str]],
) -> dict[str, dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {}
    owners: dict[Ref, str] = {}
    problems: list[str] = []
    for service in sorted(used):
        for ref in sorted(used[service]):
            kind = ref[0]
            final = (kind, names[service][ref])
            content = rewrite(component(specs[service], ref), names[service])
            existing = components.setdefault(kind, {}).get(final[1])
            if existing is None:
                components[kind][final[1]] = content
                owners[final] = f"{service} {ref[1]}"
            elif canonical(existing) != canonical(content):
                problems.append(
                    f"#/components/{kind}/{final[1]}: {service} {ref[1]} would replace"
                    f" {owners[final]}; rename one of them in its service"
                )
    if problems:
        raise BuildError(problems)
    return components


def build(specs: Mapping[str, Mapping[str, Any]], meta: Mapping[str, Any]) -> dict[str, Any]:
    """The public spec from the service specs and the meta file; BuildError when it cannot."""
    versions = sorted({str(spec.get("openapi")) for spec in specs.values()})
    if len(versions) > 1:
        raise BuildError([f"the service specs mix OpenAPI versions {', '.join(versions)}"])
    kept = {service: public_operations(service, spec) for service, spec in specs.items()}
    kept = {service: operations for service, operations in kept.items() if operations}
    used = {
        service: reachable(specs[service], [operation for _, _, operation in operations])
        for service, operations in kept.items()
    }
    names = component_names(specs, used)
    components = merged_components(specs, used, names)
    paths: dict[str, dict[str, Any]] = {}
    served_by: dict[tuple[str, str], str] = {}
    operation_ids: dict[str, str] = {}
    problems: list[str] = []
    for service in sorted(kept):
        for path, method, operation in kept[service]:
            label = f"{method.upper()} {path}"
            other = served_by.setdefault((path, method), service)
            if other != service:
                problems.append(f"{label}: public in both {other} and {service}")
                continue
            operation_id = operation.get("operationId")
            if isinstance(operation_id, str):
                first = operation_ids.setdefault(operation_id, label)
                if first != label:
                    problems.append(f"{label}: operationId {operation_id} is also {first}")
            paths.setdefault(path, {})[method] = {
                **rewrite(operation, names[service]),
                "x-service": service,
            }
    if problems:
        raise BuildError(problems)
    components.setdefault("securitySchemes", {})[SECURITY_SCHEME] = BEARER_AUTH
    document: dict[str, Any] = {
        "openapi": versions[0] if versions else "3.1.0",
        "info": dict(meta["info"]),
        "paths": paths,
        "components": components,
        "security": [{SECURITY_SCHEME: []}],
    }
    problems = lint(document)
    if problems:
        raise BuildError(problems)
    return document


def resolve(document: Mapping[str, Any], node: Any) -> Any:
    """Follow component references until a value that is not a reference."""
    for _ in range(32):
        if not isinstance(node, Mapping) or not isinstance(node.get("$ref"), str):
            return node
        kind, name = parse_ref(node["$ref"])
        node = (document.get("components") or {}).get(kind, {}).get(name, {})
    raise BuildError(["a component reference chain is deeper than 32"])


def is_page(document: Mapping[str, Any], response: Any) -> bool:
    """A JSON response body with ``items`` and ``next_cursor``: one page of a list."""
    resolved = resolve(document, response)
    if not isinstance(resolved, Mapping):
        return False
    media = (resolved.get("content") or {}).get("application/json") or {}
    schema = resolve(document, media.get("schema"))
    properties = (schema.get("properties") or {}) if isinstance(schema, Mapping) else {}
    return "items" in properties and "next_cursor" in properties


def parameters_of(
    document: Mapping[str, Any], operation: Mapping[str, Any]
) -> dict[str, Mapping[str, Any]]:
    """Each parameter by ``<in> <name>``; header names in lower case."""
    found: dict[str, Mapping[str, Any]] = {}
    for raw in operation.get("parameters") or []:
        parameter = resolve(document, raw)
        location, name = str(parameter.get("in", "")), str(parameter.get("name", ""))
        found[f"{location} {name.lower() if location == 'header' else name}"] = parameter
    return found


def operations(document: Mapping[str, Any]) -> Iterator[tuple[str, str, Mapping[str, Any]]]:
    for path, item in sorted((document.get("paths") or {}).items()):
        for method in METHODS:
            if method in item:
                yield path, method, item[method]


def lint(document: Mapping[str, Any]) -> list[str]:
    """One line per public operation that breaks an API rule (see the module docstring)."""
    problems: list[str] = []
    for path, method, operation in operations(document):
        label = f"{method.upper()} {path}"
        service = operation.get("x-service")
        if not isinstance(service, str) or not service:
            problems.append(f"{label}: no x-service")
        roles = operation.get("x-roles")
        if not isinstance(roles, list) or not roles:
            problems.append(f"{label}: x-roles must list the roles that may call it")
        else:
            unknown = sorted({str(role) for role in roles} - set(ROLES))
            if unknown:
                problems.append(f"{label}: x-roles names unknown roles {', '.join(unknown)}")
            if len(set(map(str, roles))) != len(roles):
                problems.append(f"{label}: x-roles repeats a role")
        responses = operation.get("responses") or {}
        errors = sorted(code for code in responses if str(code)[:1] in {"4", "5"})
        if not errors:
            problems.append(f"{label}: documents no problem response")
        for code in errors:
            content = resolve(document, responses[code]).get("content") or {}
            if set(content) != {PROBLEM_MEDIA}:
                problems.append(f"{label}: response {code} is not {PROBLEM_MEDIA}")
        declared = parameters_of(document, operation)
        if method == "post" and "201" in responses:
            key = declared.get("header idempotency-key")
            if key is None:
                problems.append(f"{label}: creates (201) without an Idempotency-Key header")
            elif key.get("required") is not True:
                problems.append(f"{label}: creates (201) with an optional Idempotency-Key header")
        if method == "get" and is_page(document, responses.get("200")):
            for name in ("limit", "cursor"):
                if f"query {name}" not in declared:
                    problems.append(f"{label}: a list without the {name} query parameter")
    return problems


def changelog_problems(version: str, changelog: Path) -> list[str]:
    if not changelog.is_file():
        return [f"{changelog.name} is missing"]
    headings = re.findall(r"^## (\S+)", changelog.read_text(encoding="utf-8"), flags=re.MULTILINE)
    if version not in headings:
        return [
            f"{changelog.name} has no section for {version}; add '## {version}' with the changes"
        ]
    return []


def read_meta(path: Path) -> dict[str, Any]:
    meta = load(path)
    info = meta.get("info")
    if not isinstance(info, dict) or not isinstance(info.get("title"), str):
        raise BuildError([f"{path.name}: info.title is required"])
    if not isinstance(info.get("version"), str) or not SEMVER.fullmatch(info["version"]):
        raise BuildError([f"{path.name}: info.version must be a semver string"])
    return meta


def render(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--openapi-dir", type=Path, default=OPENAPI_DIR)
    parser.add_argument(
        "--check", action="store_true", help=f"fail when {PUBLIC} differs from the build"
    )
    args = parser.parse_args(argv)
    directory: Path = args.openapi_dir
    target = directory / PUBLIC
    try:
        meta = read_meta(directory / META)
        problems = changelog_problems(meta["info"]["version"], directory / CHANGELOG)
        if problems:
            raise BuildError(problems)
        text = render(build(service_specs(directory), meta))
    except BuildError as error:
        for problem in error.problems:
            sys.stderr.write(f"public openapi: {problem}\n")
        return 1
    if args.check:
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current != text:
            sys.stderr.write(
                f"public openapi: {target.name} is stale; run make openapi-public and commit it\n"
            )
            return 1
        sys.stdout.write(f"public openapi: {target.name} is current\n")
        return 0
    target.write_text(text, encoding="utf-8")
    count = sum(1 for _ in operations(json.loads(text)))
    sys.stdout.write(f"wrote {target.name} ({count} operations)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
