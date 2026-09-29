"""The OpenAPI coverage script fails on API routes without a committed spec and contract test."""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

CONTRACTS = Path(__file__).resolve().parents[4]
REPO = CONTRACTS.parents[1]
SCRIPT = CONTRACTS / "scripts" / "check_openapi_coverage.py"

BASE_APP = """
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {}


@app.get("/ready")
def ready() -> dict[str, str]:
    return {}


@app.get("/v1/{service}/ping")
def ping() -> dict[str, str]:
    return {}
"""

EXTRA_ROUTE = """

@app.post("/v1/{service}/things", include_in_schema=False)
def things() -> dict[str, str]:
    return {}
"""


def make_service(root: Path, name: str, *, extra: bool) -> Path:
    """A service directory whose package sits under src, like the real ones."""
    service_dir = root / "services" / name
    package = service_dir / "src" / f"cwfake_{name.replace('-', '_')}"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    source = BASE_APP + (EXTRA_ROUTE if extra else "")
    (package / "main.py").write_text(textwrap.dedent(source).replace("{service}", name))
    return service_dir


def run(service_dir: Path, openapi_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(service_dir), "--openapi-dir", str(openapi_dir)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def openapi_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "openapi"
    directory.mkdir()
    return directory


def test_a_service_with_only_health_ready_and_ping_passes(
    tmp_path: Path, openapi_dir: Path
) -> None:
    result = run(make_service(tmp_path, "alpha", extra=False), openapi_dir)
    assert result.returncode == 0, result.stderr
    assert "alpha serves only health, ready and ping" in result.stdout


def test_an_api_route_without_a_spec_fails(tmp_path: Path, openapi_dir: Path) -> None:
    result = run(make_service(tmp_path, "beta", extra=True), openapi_dir)
    assert result.returncode == 1
    assert "beta: serves POST /v1/beta/things with no committed spec" in result.stderr
    assert "make openapi SERVICE=beta" in result.stderr


def test_a_spec_with_its_contract_test_passes(tmp_path: Path, openapi_dir: Path) -> None:
    service_dir = make_service(tmp_path, "gamma", extra=True)
    (openapi_dir / "gamma.v1.json").write_text("{}")
    contract = service_dir / "tests" / "contract"
    contract.mkdir(parents=True)
    (contract / "test_openapi.py").write_text("")
    result = run(service_dir, openapi_dir)
    assert result.returncode == 0, result.stderr
    assert "gamma has gamma.v1.json and its contract test" in result.stdout


def test_a_spec_without_a_contract_test_fails(tmp_path: Path, openapi_dir: Path) -> None:
    service_dir = make_service(tmp_path, "delta", extra=False)
    (openapi_dir / "delta.v1.json").write_text("{}")
    result = run(service_dir, openapi_dir)
    assert result.returncode == 1
    assert "delta: delta.v1.json is committed but" in result.stderr
    assert "tests/contract/test_openapi.py is missing" in result.stderr


def test_a_directory_without_one_app_package_is_an_error(tmp_path: Path) -> None:
    service_dir = tmp_path / "services" / "empty"
    (service_dir / "src").mkdir(parents=True)
    result = run(service_dir, tmp_path)
    assert result.returncode == 1
    assert "expected one package with a main.py under src" in result.stderr


def test_the_notification_service_has_its_spec_and_contract_test() -> None:
    result = run(REPO / "services" / "notification", CONTRACTS / "openapi")
    assert result.returncode == 0, result.stderr
