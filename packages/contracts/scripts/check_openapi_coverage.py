"""A service that serves API routes commits its OpenAPI spec and pins it with a contract test.

Every service serves ``/health``, ``/ready``, ``/v1/<service>/ping`` and FastAPI's docs routes.
A service that serves anything more needs ``packages/contracts/openapi/<service>.v1.json``
(``make openapi SERVICE=<service>``) and ``tests/contract/test_openapi.py``, which fails when the
served schema drifts from the committed file. A committed spec without that test fails too.

The script imports ``<package>.main`` by name, where ``<package>`` is the one directory under
``<service-dir>/src`` with a ``main.py``, and lists every route its ``app`` serves, including
routes left out of the schema. Run it in the service's environment, as ``make openapi-check``
does for every service::

    uv run --package compliancewatch-notification \\
        python packages/contracts/scripts/check_openapi_coverage.py services/notification

Exit status 1 with one line per finding.
"""

import argparse
import importlib
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
OPENAPI_DIR = REPO / "packages" / "contracts" / "openapi"
CONTRACT_TEST = Path("tests") / "contract" / "test_openapi.py"
SHARED_PATHS = ("/health", "/ready")
IGNORED_METHODS = frozenset({"HEAD", "OPTIONS"})


def import_package(service_dir: Path) -> str:
    """The import package of a service: the one directory under ``src`` with a ``main.py``."""
    candidates = sorted(main.parent.name for main in (service_dir / "src").glob("*/main.py"))
    if len(candidates) != 1:
        raise SystemExit(
            f"{service_dir}: expected one package with a main.py under src, found {candidates}"
        )
    return candidates[0]


def served_routes(app: Any) -> list[tuple[str, str]]:
    """``(method, path)`` for every route the app serves, flattening included routers."""
    from fastapi.routing import iter_route_contexts

    routes: set[tuple[str, str]] = set()
    for route in iter_route_contexts(app.routes):
        if not route.path:
            continue
        methods = set(route.methods or {"*"}) - IGNORED_METHODS
        routes.update((method, route.path) for method in methods or {"*"})
    return sorted(routes, key=lambda route: (route[1], route[0]))


def docs_paths(app: Any) -> set[str]:
    """The schema and docs pages FastAPI adds; none of them is part of the service's API."""
    names = ("openapi_url", "docs_url", "redoc_url", "swagger_ui_oauth2_redirect_url")
    return {path for path in (getattr(app, name, None) for name in names) if path}


def shown(path: Path) -> str:
    """A path relative to the repository when it lies inside it."""
    return str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)


def problems(
    service: str,
    routes: Iterable[tuple[str, str]],
    *,
    exempt: Iterable[str],
    spec: Path,
    contract_test: Path,
) -> list[str]:
    """Findings for one service, given the routes it serves and the paths every service has."""
    allowed = {*SHARED_PATHS, f"/v1/{service}/ping", *exempt}
    api = [f"{method} {path}" for method, path in routes if path not in allowed]
    if spec.is_file():
        if not contract_test.is_file():
            return [
                f"{service}: {spec.name} is committed but {shown(contract_test)} is missing; it"
                " pins the served schema to the spec (copy the identity service's test)"
            ]
        return []
    if api:
        return [
            f"{service}: serves {', '.join(api)} with no committed spec; run"
            f" make openapi SERVICE={service} and add {CONTRACT_TEST}"
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("service_dir", type=Path, help="the service directory, services/<name>")
    parser.add_argument("--openapi-dir", type=Path, default=OPENAPI_DIR)
    args = parser.parse_args(argv)
    service_dir: Path = args.service_dir.resolve()
    service = service_dir.name
    package = import_package(service_dir)
    # Installed services import without this; it lets the check run on a directory as well.
    sys.path.insert(0, str(service_dir / "src"))
    app = importlib.import_module(f"{package}.main").app
    routes = served_routes(app)
    spec = args.openapi_dir / f"{service}.v1.json"
    contract_test = service_dir / CONTRACT_TEST
    findings = problems(
        service, routes, exempt=docs_paths(app), spec=spec, contract_test=contract_test
    )
    for finding in findings:
        sys.stderr.write(f"openapi coverage: {finding}\n")
    if findings:
        return 1
    if spec.is_file():
        sys.stdout.write(f"openapi coverage: {service} has {spec.name} and its contract test\n")
    else:
        sys.stdout.write(f"openapi coverage: {service} serves only health, ready and ping\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
