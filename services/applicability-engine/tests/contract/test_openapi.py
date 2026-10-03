"""The served OpenAPI schema equals the committed spec
(make openapi SERVICE=applicability-engine)."""

import json
from pathlib import Path

from fastapi import FastAPI

SPEC = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "contracts"
    / "openapi"
    / "applicability-engine.v1.json"
)


def test_served_schema_matches_the_committed_spec(app: FastAPI) -> None:
    committed = json.loads(SPEC.read_text(encoding="utf-8"))
    assert app.openapi() == committed, (
        "run `make openapi SERVICE=applicability-engine` and commit the result"
    )
