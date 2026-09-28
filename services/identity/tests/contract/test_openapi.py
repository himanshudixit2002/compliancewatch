"""The served OpenAPI schema equals the committed spec (make openapi SERVICE=identity)."""

import json
from pathlib import Path

from fastapi import FastAPI

SPEC = (
    Path(__file__).resolve().parents[4] / "packages" / "contracts" / "openapi" / "identity.v1.json"
)


def test_served_schema_matches_the_committed_spec(app: FastAPI) -> None:
    served = json.loads(json.dumps(app.openapi(), sort_keys=True))
    committed = json.loads(SPEC.read_text(encoding="utf-8"))
    assert served == committed, "run: make openapi SERVICE=identity"
