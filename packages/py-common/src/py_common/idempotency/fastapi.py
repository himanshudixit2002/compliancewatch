"""Idempotent creating routes: the ``Idempotency-Key`` dependency and ``run_idempotent``.

A route that creates something declares ``key: IdempotencyKey`` and wraps its work::

    @router.post("", status_code=201, response_model=ThingOut, responses=IDEMPOTENCY_RESPONSES)
    def create(body: ThingIn, tenant: Tenant, key: IdempotencyKey, wired: Wired) -> JSONResponse:
        return run_idempotent(wired.idempotency, tenant, key, 201, lambda: make(body))

The dependency reads the header (8 to 128 printable characters) and the body, and fingerprints
method, path and body. The spec marks the header required, and a request without it is answered
with the 428 problem idempotency-key-required rather than request-invalid. ``run_idempotent``
claims the key and runs ``produce``. A 2xx or 4xx it returns is recorded and replayed, with the
header ``Idempotent-Replayed: true``, to every retry with the same key and request for 24 hours;
the same key with another request is a 422, and a retry while the first request runs is a 409. A
5xx is never recorded: the key is released, as it is when ``produce`` raises, so the retry runs.

By default each key statement runs in its own short transaction (the store's). Pass
``recorder=store.recorder(connection)`` to run them inside the caller's transaction instead: the
key row then commits with the business write, or rolls back with it when ``produce`` raises, and
run_idempotent leaves the failed transaction alone.
"""

import json
from collections.abc import Callable
from typing import Annotated, Any, Final

from fastapi import Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from domain_kernel.ids import TenantId
from py_common.idempotency.errors import IDEMPOTENCY_KEY_HEADER as IDEMPOTENCY_KEY_HEADER
from py_common.idempotency.errors import (
    IdempotencyKeyReusedError,
    IdempotencyRequestInFlightError,
)
from py_common.idempotency.store import (
    MAX_KEY_LENGTH,
    MIN_KEY_LENGTH,
    IdempotencyRecorder,
    IdempotencyRequest,
    IdempotencyStore,
    InFlight,
    Replay,
    Reused,
    StoredResponse,
)
from py_common.logging import get_logger
from py_common.problems import problem_responses

REPLAYED_HEADER: Final = "Idempotent-Replayed"
KEY_PATTERN: Final = r"^[!-~]+$"
"""Printable ASCII without spaces, such as a UUID or a ULID."""
IDEMPOTENCY_RESPONSES: Final = problem_responses(409, 422, 428)
"""The problems an idempotent route adds to its ``responses``."""
_NOT_REPLAYED: Final = frozenset({"content-length", "content-type"})

log = get_logger(__name__)


async def idempotency_key(
    request: Request,
    key: Annotated[
        str,
        Header(
            alias=IDEMPOTENCY_KEY_HEADER,
            min_length=MIN_KEY_LENGTH,
            max_length=MAX_KEY_LENGTH,
            pattern=KEY_PATTERN,
            description=(
                "A new value for each new request, such as a UUID; a retry sends the same value "
                "and gets the first response back for 24 hours"
            ),
        ),
    ],
) -> IdempotencyRequest:
    """The key with the request it came with. A request without the header never gets here:
    py-common's validation handler answers it with IdempotencyKeyRequiredError (428). Starlette
    keeps the body it read for the route's own parameters, so reading it here costs nothing."""
    return IdempotencyRequest.of(key, request.method, request.url.path, await request.body())


IdempotencyKey = Annotated[IdempotencyRequest, Depends(idempotency_key)]
"""The dependency a creating route declares: ``key: IdempotencyKey``."""


def run_idempotent(
    store: IdempotencyStore,
    tenant: TenantId,
    key: IdempotencyRequest,
    status_code: int,
    produce: Callable[[], BaseModel | JSONResponse],
    *,
    recorder: IdempotencyRecorder | None = None,
) -> JSONResponse:
    """Run ``produce`` once per key: its model is answered with ``status_code``, a
    ``JSONResponse`` as it is. Replays, a reused key (422) and a running request (409) never
    call it."""
    keeper: IdempotencyRecorder = store if recorder is None else recorder
    outcome = keeper.begin(tenant, key)
    if isinstance(outcome, Replay):
        log.info("idempotency.replayed", path=key.path, status_code=outcome.response.status_code)
        return _replayed(outcome.response)
    if isinstance(outcome, Reused):
        raise IdempotencyKeyReusedError()
    if isinstance(outcome, InFlight):
        raise IdempotencyRequestInFlightError()
    try:
        response = _as_response(produce(), status_code)
    except BaseException:
        if recorder is None:
            _abandon(store, tenant, key)
        raise
    if response.status_code >= 500:
        keeper.abandon(tenant, key)
        return response
    keeper.complete(tenant, key, _stored(response))
    return response


def _as_response(produced: BaseModel | JSONResponse, status_code: int) -> JSONResponse:
    if isinstance(produced, JSONResponse):
        return produced
    body = produced.model_dump(mode="json", by_alias=True)
    return JSONResponse(content=body, status_code=status_code)


def _stored(response: JSONResponse) -> StoredResponse:
    body: Any = json.loads(bytes(response.body))
    headers = {name: value for name, value in response.headers.items() if name not in _NOT_REPLAYED}
    return StoredResponse(response.status_code, body, headers)


def _replayed(stored: StoredResponse) -> JSONResponse:
    return JSONResponse(
        content=stored.body,
        status_code=stored.status_code,
        headers={**stored.headers, REPLAYED_HEADER: "true"},
    )


def _abandon(store: IdempotencyStore, tenant: TenantId, key: IdempotencyRequest) -> None:
    """Release the key after ``produce`` failed. When that fails too, the original error still
    propagates and the key frees itself when its lease runs out."""
    try:
        store.abandon(tenant, key)
    except Exception:
        log.warning("idempotency.abandon_failed", path=key.path, exc_info=True)
