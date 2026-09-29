"""The OpenAPI compatibility script accepts additive changes and refuses breaking ones."""

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

CONTRACTS = Path(__file__).resolve().parents[4]
SCRIPT = CONTRACTS / "scripts" / "check_openapi_compat.py"
OPENAPI = CONTRACTS / "openapi"
TABLE_HEAD = "| Spec | Operation | Reason | ADR |\n| --- | --- | --- | --- |\n"

Edit = Callable[[dict[str, Any]], None]


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False
    )


def compare(base: Path, head: Path) -> subprocess.CompletedProcess[str]:
    return run("--base-dir", str(base), "--head-dir", str(head))


def edit_spec(root: Path, name: str, change: Edit) -> None:
    path = root / name
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document), encoding="utf-8")


def schemas(document: dict[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = document["components"]["schemas"]
    return found


def write_rows(root: Path, *rows: str) -> None:
    (root / "BREAKING.md").write_text(TABLE_HEAD + "".join(f"{row}\n" for row in rows))


@pytest.fixture
def base(tmp_path: Path) -> Path:
    copy = tmp_path / "base"
    shutil.copytree(OPENAPI, copy)
    return copy


@pytest.fixture
def head(tmp_path: Path) -> Path:
    copy = tmp_path / "head"
    shutil.copytree(OPENAPI, copy)
    return copy


def test_identical_specs_are_compatible(base: Path, head: Path) -> None:
    result = compare(base, head)
    assert result.returncode == 0, result.stderr
    assert "backward compatible" in result.stdout
    assert "identity.v1.json" in result.stdout


def test_the_committed_break_log_parses(head: Path) -> None:
    result = compare(head, head)
    assert result.returncode == 0, result.stderr
    assert "error:" not in result.stderr


def test_a_removed_path_is_refused(base: Path, head: Path) -> None:
    edit_spec(head, "identity.v1.json", lambda doc: doc["paths"].pop("/v1/identity/consents"))
    result = compare(base, head)
    assert result.returncode == 1
    assert "identity.v1.json GET /v1/identity/consents: path removed" in result.stderr
    assert "identity.v1.json POST /v1/identity/consents: path removed" in result.stderr


def test_a_removed_operation_is_refused(base: Path, head: Path) -> None:
    edit_spec(
        head, "identity.v1.json", lambda doc: doc["paths"]["/v1/identity/consents"].pop("post")
    )
    result = compare(base, head)
    assert result.returncode == 1
    assert "POST /v1/identity/consents: operation removed" in result.stderr
    assert "GET /v1/identity/consents" not in result.stderr


def test_a_removed_success_response_is_refused(base: Path, head: Path) -> None:
    def drop(doc: dict[str, Any]) -> None:
        doc["paths"]["/v1/identity/billing/plans"]["get"]["responses"].pop("200")

    edit_spec(head, "identity.v1.json", drop)
    result = compare(base, head)
    assert result.returncode == 1
    assert "GET /v1/identity/billing/plans: response 200 removed" in result.stderr


def test_a_removed_response_property_is_refused(base: Path, head: Path) -> None:
    edit_spec(
        head,
        "llm-gateway.v1.json",
        lambda doc: schemas(doc)["UsageOut"]["properties"].pop("spent_inr"),
    )
    result = compare(base, head)
    assert result.returncode == 1
    assert (
        "llm-gateway.v1.json GET /v1/llm-gateway/usage: response 200 body.spent_inr removed"
        in result.stderr
    )


def test_a_newly_required_body_field_is_refused(base: Path, head: Path) -> None:
    def require(doc: dict[str, Any]) -> None:
        consent = schemas(doc)["ConsentIn"]
        consent["properties"]["channel"] = {"type": "string"}
        consent["required"].append("channel")

    edit_spec(head, "identity.v1.json", require)
    result = compare(base, head)
    assert result.returncode == 1
    assert "POST /v1/identity/consents: request body.channel became required" in result.stderr


def test_a_newly_required_query_parameter_is_refused(base: Path, head: Path) -> None:
    def require(doc: dict[str, Any]) -> None:
        for parameter in doc["paths"]["/v1/llm-gateway/usage"]["get"]["parameters"]:
            if parameter["name"] == "month":
                parameter["required"] = True

    edit_spec(head, "llm-gateway.v1.json", require)
    result = compare(base, head)
    assert result.returncode == 1
    assert "GET /v1/llm-gateway/usage: query parameter month became required" in result.stderr


def test_a_new_required_header_is_refused(base: Path, head: Path) -> None:
    def add(doc: dict[str, Any]) -> None:
        operation = doc["paths"]["/v1/identity/billing/plans"]["get"]
        operation["parameters"] = [
            {"in": "header", "name": "X-Api-Key", "required": True, "schema": {"type": "string"}}
        ]

    edit_spec(head, "identity.v1.json", add)
    result = compare(base, head)
    assert result.returncode == 1
    assert "header parameter x-api-key became required" in result.stderr


def test_a_narrowed_enum_is_refused(base: Path, head: Path) -> None:
    edit_spec(
        head, "notification.v1.json", lambda doc: schemas(doc)["Channel"].update(enum=["whatsapp"])
    )
    result = compare(base, head)
    assert result.returncode == 1
    assert (
        "PUT /v1/notification/preferences/{channel}/{recipient}: path parameter channel no longer"
        ' accepts "email"' in result.stderr
    )
    assert 'POST /v1/notification/send: request body.channel no longer accepts "email"' in (
        result.stderr
    )


def test_a_widened_enum_is_compatible(base: Path, head: Path) -> None:
    edit_spec(
        head,
        "notification.v1.json",
        lambda doc: schemas(doc)["Channel"].update(enum=["whatsapp", "email", "sms"]),
    )
    result = compare(base, head)
    assert result.returncode == 0, result.stderr


def test_a_request_type_change_is_refused(base: Path, head: Path) -> None:
    edit_spec(
        head,
        "identity.v1.json",
        lambda doc: schemas(doc)["ConsentIn"]["properties"]["subject"].update(type="integer"),
    )
    result = compare(base, head)
    assert result.returncode == 1
    assert "request body.subject type changed from string to integer" in result.stderr


def test_a_response_that_may_now_be_null_is_refused(base: Path, head: Path) -> None:
    def nullable(doc: dict[str, Any]) -> None:
        properties = schemas(doc)["UsageOut"]["properties"]
        properties["ratio"] = {"anyOf": [{"type": "string"}, {"type": "null"}]}

    edit_spec(head, "llm-gateway.v1.json", nullable)
    result = compare(base, head)
    assert result.returncode == 1
    assert "response 200 body.ratio type changed from string to null|string" in result.stderr


def test_a_request_field_that_accepts_null_is_compatible(base: Path, head: Path) -> None:
    def nullable(doc: dict[str, Any]) -> None:
        properties = schemas(doc)["ConsentIn"]["properties"]
        properties["evidence"] = {"anyOf": [{"type": "string"}, {"type": "null"}]}

    edit_spec(head, "identity.v1.json", nullable)
    result = compare(base, head)
    assert result.returncode == 0, result.stderr


def test_an_additive_route_and_optional_fields_are_compatible(base: Path, head: Path) -> None:
    def add(doc: dict[str, Any]) -> None:
        doc["paths"]["/v1/identity/consents/export"] = doc["paths"]["/v1/identity/billing/plans"]
        schemas(doc)["ConsentIn"]["properties"]["channel"] = {"type": "string"}
        schemas(doc)["ConsentOut"]["properties"]["channel"] = {"type": "string"}

    edit_spec(head, "identity.v1.json", add)
    result = compare(base, head)
    assert result.returncode == 0, result.stderr


def test_a_spec_that_is_new_on_the_branch_is_skipped(base: Path, head: Path) -> None:
    (base / "notification.v1.json").unlink()
    edit_spec(head, "notification.v1.json", lambda doc: doc["paths"].clear())
    result = compare(base, head)
    assert result.returncode == 0, result.stderr
    assert "notification.v1.json" not in result.stdout


def test_a_removed_spec_is_refused(base: Path, head: Path) -> None:
    (head / "profile.v1.json").unlink()
    result = compare(base, head)
    assert result.returncode == 1
    assert "profile.v1.json POST /v1/profile/entities: path removed" in result.stderr


def test_a_new_break_log_row_allows_the_listed_break(base: Path, head: Path) -> None:
    edit_spec(
        head, "identity.v1.json", lambda doc: doc["paths"]["/v1/identity/consents"].pop("post")
    )
    write_rows(
        head,
        "| `identity.v1.json` | `POST /v1/identity/consents` | Consents move to a new route |"
        " ADR-099 |",
    )
    result = compare(base, head)
    assert result.returncode == 0, result.stderr
    assert "allowed by BREAKING.md: identity.v1.json POST /v1/identity/consents" in result.stdout


def test_a_row_already_on_the_base_allows_nothing_new(base: Path, head: Path) -> None:
    row = "| identity.v1.json | POST /v1/identity/consents | An earlier break | ADR-099 |"
    write_rows(base, row)
    write_rows(head, row)
    edit_spec(
        head, "identity.v1.json", lambda doc: doc["paths"]["/v1/identity/consents"].pop("post")
    )
    result = compare(base, head)
    assert result.returncode == 1
    assert "POST /v1/identity/consents: operation removed" in result.stderr


def test_a_new_row_that_matches_no_break_is_refused(base: Path, head: Path) -> None:
    write_rows(head, "| identity.v1.json | GET /v1/identity/consents | Planned | ADR-099 |")
    result = compare(base, head)
    assert result.returncode == 1
    assert "GET /v1/identity/consents matches no breaking change" in result.stderr


def test_a_row_without_an_adr_is_refused(base: Path, head: Path) -> None:
    write_rows(head, "| identity.v1.json | GET /v1/identity/consents | Planned | none |")
    result = compare(base, head)
    assert result.returncode == 1
    assert "a break needs a reason and an ADR-NNN" in result.stderr


def test_an_unknown_base_ref_is_an_error() -> None:
    result = run("--base-ref", "cw-no-such-ref")
    assert result.returncode == 1
    assert "git archive cw-no-such-ref failed" in result.stderr
