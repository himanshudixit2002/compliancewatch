"""The public API spec is the build of the services' public operations and follows the API rules."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

CONTRACTS = Path(__file__).resolve().parents[4]
SCRIPT = CONTRACTS / "scripts" / "build_public_openapi.py"
OPENAPI = CONTRACTS / "openapi"
PUBLIC = json.loads((OPENAPI / "public.v1.json").read_text(encoding="utf-8"))
META = json.loads((OPENAPI / "public.meta.json").read_text(encoding="utf-8"))
METHODS = ("get", "put", "post", "delete", "patch")
ROLES = {
    "owner",
    "staff",
    "ca_admin",
    "ca_staff",
    "compliance_lead",
    "analyst",
    "reviewer",
    "admin",
}
"""The tenant members' roles and the regulatory team's (``domain_kernel.access``)."""
PROBLEM_REF = "#/components/schemas/Problem"
PROBLEM = {
    "properties": {"status": {"type": "integer"}, "title": {"type": "string"}},
    "title": "Problem",
    "type": "object",
}
TENANT_ROLES = ["owner", "staff"]


def public_operations() -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, item[method])
        for path, item in sorted(PUBLIC["paths"].items())
        for method in METHODS
        if method in item
    ]


def ids(operation: tuple[str, str, dict[str, Any]]) -> str:
    return f"{operation[1].upper()} {operation[0]}"


def resolve(node: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        kind, name = node["$ref"].removeprefix("#/components/").split("/")
        node = PUBLIC["components"][kind][name]
    return node


def declared(operation: dict[str, Any]) -> set[str]:
    return {
        f"{p['in']} {p['name'].lower() if p['in'] == 'header' else p['name']}"
        for p in operation.get("parameters", [])
    }


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False
    )


# ---- the committed spec ------------------------------------------------------------------------


def test_the_committed_spec_is_the_build_output() -> None:
    result = run("--check")
    assert result.returncode == 0, result.stderr
    assert "public.v1.json is current" in result.stdout


def test_info_comes_from_the_meta_file_and_every_operation_needs_a_bearer_token() -> None:
    assert PUBLIC["info"] == META["info"]
    assert PUBLIC["security"] == [{"bearerAuth": []}]
    assert PUBLIC["components"]["securitySchemes"]["bearerAuth"]["scheme"] == "bearer"


def test_the_changelog_names_the_current_version() -> None:
    changelog = (OPENAPI / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## {re.escape(META['info']['version'])}$", changelog, re.MULTILINE)


def test_each_service_operation_tagged_public_is_in_the_spec_under_its_service() -> None:
    expected = set()
    for path in OPENAPI.glob("*.v1.json"):
        if path.name == "public.v1.json":
            continue
        service = path.name.removesuffix(".v1.json")
        spec = json.loads(path.read_text(encoding="utf-8"))
        for route, item in spec["paths"].items():
            for method, operation in item.items():
                if "public" in operation.get("tags", []):
                    expected.add((method, route, service))
    found = {(method, path, op["x-service"]) for path, method, op in public_operations()}
    assert found == expected
    assert ("get", "/v1/ontology", "profile") in found


@pytest.mark.parametrize("operation", public_operations(), ids=ids)
def test_every_public_operation_names_its_roles_and_answers_problems(
    operation: tuple[str, str, dict[str, Any]],
) -> None:
    _, _, op = operation
    assert op["x-roles"]
    assert set(op["x-roles"]) <= ROLES
    errors = {code: response for code, response in op["responses"].items() if code[0] in "45"}
    assert errors
    for response in errors.values():
        assert response["content"]["application/problem+json"]["schema"] == {"$ref": PROBLEM_REF}


@pytest.mark.parametrize(
    "operation",
    [op for op in public_operations() if op[1] == "post" and "201" in op[2]["responses"]],
    ids=ids,
)
def test_creating_posts_declare_an_idempotency_key(
    operation: tuple[str, str, dict[str, Any]],
) -> None:
    assert "header idempotency-key" in declared(operation[2])
    [key] = [p for p in operation[2]["parameters"] if p["name"].lower() == "idempotency-key"]
    assert key["required"] is True, "the services refuse a creating request without it (428)"


def test_lists_declare_limit_and_cursor() -> None:
    lists = []
    for path, method, op in public_operations():
        body = op["responses"].get("200", {}).get("content", {}).get("application/json", {})
        schema = resolve(body.get("schema", {}))
        if method == "get" and "next_cursor" in schema.get("properties", {}):
            lists.append(path)
            assert {"query limit", "query cursor"} <= declared(op)
    assert lists == [
        "/v1/businesses",
        "/v1/businesses/{business_id}/obligations",
        "/v1/changes",
        "/v1/changes/{rule_version_id}/impact",
    ]


def test_only_components_the_operations_reach_are_copied() -> None:
    schemas = PUBLIC["components"]["schemas"]
    assert "Problem" in schemas
    assert "HealthResponse" not in schemas
    assert "SnapshotOut" not in schemas


@pytest.mark.parametrize("operation", public_operations(), ids=ids)
def test_every_public_operation_takes_the_spec_wide_bearer_token(
    operation: tuple[str, str, dict[str, Any]],
) -> None:
    assert "security" not in operation[2]
    assert list(PUBLIC["components"]["securitySchemes"]) == ["bearerAuth"]


# ---- the builder -------------------------------------------------------------------------------


def operation(
    operation_id: str,
    *,
    tags: tuple[str, ...] = ("public",),
    response: dict[str, Any] | None = None,
    status: str = "200",
    parameters: list[dict[str, Any]] | None = None,
    roles: list[str] | None = None,
) -> dict[str, Any]:
    body = response if response is not None else {"type": "object"}
    op: dict[str, Any] = {
        "operationId": operation_id,
        "tags": list(tags),
        "responses": {
            status: {"content": {"application/json": {"schema": body}}, "description": "OK"},
            "422": {
                "content": {"application/problem+json": {"schema": {"$ref": PROBLEM_REF}}},
                "description": "Unprocessable Entity",
            },
        },
        "parameters": parameters or [],
    }
    if roles is not None or "public" in tags:
        op["x-roles"] = roles if roles is not None else TENANT_ROLES
    return op


def spec(paths: dict[str, Any], schemas: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "service", "version": "0.1.0"},
        "paths": paths,
        "components": {"schemas": {"Problem": PROBLEM, **(schemas or {})}},
    }


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "public.meta.json").write_text(
        json.dumps({"info": {"title": "Public", "version": "1.2.0"}})
    )
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## 1.2.0\n\n- Something.\n")
    return tmp_path


def write(directory: Path, name: str, document: dict[str, Any]) -> None:
    (directory / name).write_text(json.dumps(document), encoding="utf-8")


def build(directory: Path, *args: str) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    result = run("--openapi-dir", str(directory), *args)
    target = directory / "public.v1.json"
    document = json.loads(target.read_text()) if target.is_file() else {}
    return result, document


def ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def test_the_build_keeps_public_operations_and_the_components_they_reach(workspace: Path) -> None:
    write(
        workspace,
        "alpha.v1.json",
        spec(
            {
                "/v1/things": {"get": operation("list_things", response=ref("Thing"))},
                "/v1/alpha/admin": {"get": operation("admin", tags=("alpha",))},
            },
            {
                "Thing": {"properties": {"part": ref("Part")}, "type": "object"},
                "Part": {"type": "string"},
                "Unused": {"type": "integer"},
            },
        ),
    )
    result, document = build(workspace)
    assert result.returncode == 0, result.stderr
    assert "wrote public.v1.json (1 operations)" in result.stdout
    assert list(document["paths"]) == ["/v1/things"]
    assert document["paths"]["/v1/things"]["get"]["x-service"] == "alpha"
    assert sorted(document["components"]["schemas"]) == ["Part", "Problem", "Thing"]
    assert document["info"] == {"title": "Public", "version": "1.2.0"}
    assert build(workspace, "--check")[0].returncode == 0


def test_an_operations_own_security_is_left_to_the_spec_wide_bearer_token(
    workspace: Path,
) -> None:
    secured = {**operation("list_things"), "security": [{"HTTPBearer": []}]}
    alpha = spec({"/v1/things": {"get": secured}})
    alpha["components"]["securitySchemes"] = {"HTTPBearer": {"type": "http", "scheme": "bearer"}}
    write(workspace, "alpha.v1.json", alpha)
    result, document = build(workspace)
    assert result.returncode == 0, result.stderr
    assert "security" not in document["paths"]["/v1/things"]["get"]
    assert document["security"] == [{"bearerAuth": []}]
    assert list(document["components"]["securitySchemes"]) == ["bearerAuth"]


def test_identical_components_are_shared_and_clashing_ones_are_prefixed(workspace: Path) -> None:
    write(
        workspace,
        "alpha.v1.json",
        spec(
            {"/v1/alpha": {"get": operation("read_alpha", response=ref("Out"))}},
            {"Out": {"properties": {"code": ref("Code")}, "type": "object"}, "Code": {"enum": [1]}},
        ),
    )
    write(
        workspace,
        "llm-gateway.v1.json",
        spec(
            {"/v1/beta": {"get": operation("read_beta", response=ref("Out"))}},
            {"Out": {"properties": {"code": ref("Code")}, "type": "object"}, "Code": {"enum": [2]}},
        ),
    )
    result, document = build(workspace)
    assert result.returncode == 0, result.stderr
    schemas = document["components"]["schemas"]
    # Code differs, so Out differs too once its reference follows the rename.
    assert sorted(schemas) == [
        "AlphaCode",
        "AlphaOut",
        "LlmGatewayCode",
        "LlmGatewayOut",
        "Problem",
    ]
    assert schemas["AlphaOut"]["properties"]["code"] == ref("AlphaCode")
    beta = document["paths"]["/v1/beta"]["get"]
    assert beta["responses"]["200"]["content"]["application/json"]["schema"] == ref("LlmGatewayOut")
    assert beta["responses"]["422"]["content"]["application/problem+json"]["schema"] == ref(
        "Problem"
    )


def test_a_prefixed_name_that_meets_another_component_fails(workspace: Path) -> None:
    write(
        workspace,
        "alpha.v1.json",
        spec(
            {"/v1/alpha": {"get": operation("read_alpha", response=ref("Out"))}},
            {"Out": {"type": "string"}},
        ),
    )
    write(
        workspace,
        "beta.v1.json",
        spec(
            {"/v1/beta": {"get": operation("read_beta", response=ref("Out"))}},
            {"Out": {"type": "integer"}},
        ),
    )
    write(
        workspace,
        "gamma.v1.json",
        spec(
            {"/v1/gamma": {"get": operation("read_gamma", response=ref("AlphaOut"))}},
            {"AlphaOut": {"type": "boolean"}},
        ),
    )
    result, _ = build(workspace)
    assert result.returncode == 1
    assert "#/components/schemas/AlphaOut: gamma AlphaOut would replace alpha Out" in result.stderr


def test_the_same_path_and_method_in_two_services_fails(workspace: Path) -> None:
    write(workspace, "alpha.v1.json", spec({"/v1/x": {"get": operation("alpha_x")}}))
    write(workspace, "beta.v1.json", spec({"/v1/x": {"get": operation("beta_x")}}))
    result, _ = build(workspace)
    assert result.returncode == 1
    assert "GET /v1/x: public in both alpha and beta" in result.stderr


def test_a_repeated_operation_id_fails(workspace: Path) -> None:
    write(workspace, "alpha.v1.json", spec({"/v1/x": {"get": operation("same")}}))
    write(workspace, "beta.v1.json", spec({"/v1/y": {"get": operation("same")}}))
    result, _ = build(workspace)
    assert result.returncode == 1
    assert "GET /v1/y: operationId same is also GET /v1/x" in result.stderr


def test_a_reference_to_a_missing_component_fails(workspace: Path) -> None:
    write(workspace, "alpha.v1.json", spec({"/v1/x": {"get": operation("x", response=ref("No"))}}))
    result, _ = build(workspace)
    assert result.returncode == 1
    assert "#/components/schemas/No is referenced but not defined" in result.stderr


@pytest.mark.parametrize(
    ("roles", "message"),
    [
        ([], "GET /v1/x: x-roles must list the roles that may call it"),
        (["owner", "partner"], "GET /v1/x: x-roles names unknown roles partner"),
        (["owner", "owner"], "GET /v1/x: x-roles repeats a role"),
    ],
)
def test_x_roles_must_name_known_tenant_roles(
    workspace: Path, roles: list[str], message: str
) -> None:
    write(workspace, "alpha.v1.json", spec({"/v1/x": {"get": operation("x", roles=roles)}}))
    result, _ = build(workspace)
    assert result.returncode == 1
    assert message in result.stderr


def test_x_roles_may_name_the_regulatory_team_beside_the_tenant_members(workspace: Path) -> None:
    roles = ["owner", "ca_admin", "analyst", "reviewer", "admin"]
    write(workspace, "alpha.v1.json", spec({"/v1/x": {"get": operation("x", roles=roles)}}))
    result, document = build(workspace)
    assert result.returncode == 0, result.stderr
    assert document["paths"]["/v1/x"]["get"]["x-roles"] == roles


def test_the_known_roles_are_the_kernels_member_and_regulatory_roles() -> None:
    from domain_kernel.access import REGULATORY_ROLES, TENANT_MEMBER_ROLES

    assert {role.value for role in TENANT_MEMBER_ROLES | REGULATORY_ROLES} == ROLES


def test_error_responses_must_be_problem_documents(workspace: Path) -> None:
    plain = operation("x")
    plain["responses"]["404"] = {"content": {"application/json": {}}, "description": "Not Found"}
    silent = operation("y")
    del silent["responses"]["422"]
    write(workspace, "alpha.v1.json", spec({"/v1/x": {"get": plain}, "/v1/y": {"get": silent}}))
    result, _ = build(workspace)
    assert result.returncode == 1
    assert "GET /v1/x: response 404 is not application/problem+json" in result.stderr
    assert "GET /v1/y: documents no problem response" in result.stderr


def test_a_creating_post_needs_a_required_idempotency_key(workspace: Path) -> None:
    key = {"in": "header", "name": "Idempotency-Key", "schema": {"type": "string"}}
    required = {**key, "required": True}
    write(
        workspace,
        "alpha.v1.json",
        spec(
            {
                "/v1/w": {"post": operation("create_w", status="201", parameters=[key])},
                "/v1/x": {"post": operation("create_x", status="201")},
                "/v1/y": {"post": operation("create_y", status="201", parameters=[required])},
                "/v1/z": {"post": operation("ask_z")},
            }
        ),
    )
    result, _ = build(workspace)
    assert result.returncode == 1
    assert result.stderr.splitlines() == [
        "public openapi: POST /v1/w: creates (201) with an optional Idempotency-Key header",
        "public openapi: POST /v1/x: creates (201) without an Idempotency-Key header",
    ]


def test_a_list_needs_limit_and_cursor(workspace: Path) -> None:
    limit = {"in": "query", "name": "limit", "schema": {"type": "integer"}}
    write(
        workspace,
        "alpha.v1.json",
        spec(
            {"/v1/x": {"get": operation("list_x", response=ref("Page"), parameters=[limit])}},
            {
                "Page": {
                    "properties": {"items": {"type": "array"}, "next_cursor": {"type": "string"}},
                    "type": "object",
                }
            },
        ),
    )
    result, _ = build(workspace)
    assert result.returncode == 1
    assert result.stderr.splitlines() == [
        "public openapi: GET /v1/x: a list without the cursor query parameter"
    ]


def test_the_changelog_must_have_the_meta_version(workspace: Path) -> None:
    write(workspace, "alpha.v1.json", spec({"/v1/x": {"get": operation("x")}}))
    (workspace / "CHANGELOG.md").write_text("# Changelog\n\n## 1.1.0\n")
    result, _ = build(workspace)
    assert result.returncode == 1
    assert "CHANGELOG.md has no section for 1.2.0" in result.stderr


def test_the_meta_version_must_be_semver(workspace: Path) -> None:
    meta = {"info": {"title": "Public", "version": "1"}}
    (workspace / "public.meta.json").write_text(json.dumps(meta))
    result, _ = build(workspace)
    assert result.returncode == 1
    assert "info.version must be a semver string" in result.stderr


def test_check_reports_a_stale_spec(workspace: Path) -> None:
    write(workspace, "alpha.v1.json", spec({"/v1/x": {"get": operation("x")}}))
    assert build(workspace)[0].returncode == 0
    write(workspace, "alpha.v1.json", spec({"/v1/y": {"get": operation("y")}}))
    result, _ = build(workspace, "--check")
    assert result.returncode == 1
    assert "public.v1.json is stale; run make openapi-public" in result.stderr


def test_the_committed_specs_build_in_a_copy(tmp_path: Path) -> None:
    copy = tmp_path / "openapi"
    shutil.copytree(OPENAPI, copy)
    (copy / "public.v1.json").unlink()
    result, document = build(copy)
    assert result.returncode == 0, result.stderr
    assert document == PUBLIC
