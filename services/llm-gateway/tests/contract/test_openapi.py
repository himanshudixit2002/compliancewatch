"""The committed OpenAPI spec must match what the app serves."""

import json
from pathlib import Path

from fastapi import FastAPI

SPEC = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "contracts"
    / "openapi"
    / "llm-gateway.v1.json"
)
HINT = (
    "packages/contracts/openapi/llm-gateway.v1.json is stale: "
    "run `make openapi SERVICE=llm-gateway` and commit the result"
)


def test_openapi_matches_the_committed_spec(app: FastAPI) -> None:
    served = json.loads(json.dumps(app.openapi(), sort_keys=True))
    committed = json.loads(SPEC.read_text(encoding="utf-8"))
    assert served == committed, HINT
