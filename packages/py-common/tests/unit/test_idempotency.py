"""Idempotency keys in memory and through a route: replay, a reused key, a running request,
expiry after 24 hours, the purge, the header rules, what is never recorded, and the recorder
that runs inside the caller's transaction."""

import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel

from domain_kernel.errors import PROBLEM_TYPE_PREFIX
from domain_kernel.ids import TenantId
from py_common.app import create_app
from py_common.idempotency import (
    IN_FLIGHT_LEASE,
    REPLAY_WINDOW,
    IdempotencyKeyRequiredError,
    IdempotencyKeyReusedError,
    IdempotencyRequest,
    IdempotencyRequestInFlightError,
    InFlight,
    MemoryIdempotencyStore,
    Outcome,
    Replay,
    Reused,
    Started,
    StoredResponse,
    fingerprint,
)
from py_common.idempotency.__main__ import main as purge_main
from py_common.idempotency.fastapi import (
    IDEMPOTENCY_KEY_HEADER,
    IDEMPOTENCY_RESPONSES,
    REPLAYED_HEADER,
    IdempotencyKey,
    run_idempotent,
)
from py_common.problems import DEFAULT_STATUS_BY_ERROR, PROBLEM_MEDIA_TYPE

TENANT = TenantId(UUID(int=1))
OTHER_TENANT = TenantId(UUID(int=2))
START = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
KEY = "0b7e2a54-first-try"
PATH = "/t/things"


def request(body: bytes = b'{"name": "a"}', key: str = KEY, path: str = PATH) -> IdempotencyRequest:
    return IdempotencyRequest.of(key, "post", path, body)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock: Clock) -> MemoryIdempotencyStore:
    return MemoryIdempotencyStore(clock=clock)


CREATED = StoredResponse(201, {"id": 7}, {"location": "/t/things/7"})


# ---- the request ------------------------------------------------------------------------------


def test_the_fingerprint_covers_method_path_and_body() -> None:
    base = fingerprint("POST", PATH, b"{}")
    assert len(base) == 64
    assert int(base, 16) >= 0
    assert fingerprint("post", PATH, b"{}") == base
    assert fingerprint("PUT", PATH, b"{}") != base
    assert fingerprint("POST", "/t/other", b"{}") != base
    assert fingerprint("POST", PATH, b"{ }") != base


@pytest.mark.parametrize("key", ["short", "k" * 129])
def test_a_key_outside_8_to_128_characters_is_not_a_request(key: str) -> None:
    with pytest.raises(ValueError, match="8 to 128"):
        request(key=key)


def test_a_request_needs_a_full_fingerprint() -> None:
    with pytest.raises(ValueError, match="64 hex"):
        IdempotencyRequest(KEY, "POST", PATH, "abc")


# ---- the memory store -------------------------------------------------------------------------


def test_the_first_request_starts_and_its_response_is_replayed(
    store: MemoryIdempotencyStore,
) -> None:
    assert store.begin(TENANT, request()) == Started()
    store.complete(TENANT, request(), CREATED)
    assert store.begin(TENANT, request()) == Replay(CREATED)
    assert store.begin(TENANT, request()) == Replay(CREATED)


def test_the_same_key_with_another_request_is_reused(store: MemoryIdempotencyStore) -> None:
    store.begin(TENANT, request())
    assert store.begin(TENANT, request(body=b'{"name": "b"}')) == Reused()
    store.complete(TENANT, request(), CREATED)
    assert store.begin(TENANT, request(path="/t/other")) == Reused()


def test_a_retry_while_the_first_request_runs_is_in_flight(store: MemoryIdempotencyStore) -> None:
    store.begin(TENANT, request())
    assert store.begin(TENANT, request()) == InFlight()


def test_keys_belong_to_a_tenant(store: MemoryIdempotencyStore) -> None:
    store.begin(TENANT, request())
    store.complete(TENANT, request(), CREATED)
    assert store.begin(OTHER_TENANT, request()) == Started()


def test_a_response_is_replayed_for_24_hours(store: MemoryIdempotencyStore, clock: Clock) -> None:
    store.begin(TENANT, request())
    clock.now += timedelta(minutes=1)
    store.complete(TENANT, request(), CREATED)
    clock.now += REPLAY_WINDOW - timedelta(seconds=1)
    assert store.begin(TENANT, request()) == Replay(CREATED)
    clock.now += timedelta(seconds=1)
    assert store.begin(TENANT, request(body=b"another")) == Started()


def test_a_claim_without_a_response_frees_the_key_after_the_lease(
    store: MemoryIdempotencyStore, clock: Clock
) -> None:
    store.begin(TENANT, request())
    clock.now += IN_FLIGHT_LEASE - timedelta(seconds=1)
    assert store.begin(TENANT, request()) == InFlight()
    clock.now += timedelta(seconds=1)
    assert store.begin(TENANT, request()) == Started()


def test_a_late_response_does_not_overwrite_the_request_that_took_the_key_over(
    store: MemoryIdempotencyStore, clock: Clock
) -> None:
    store.begin(TENANT, request())
    clock.now += IN_FLIGHT_LEASE
    newer = request(body=b"newer")
    assert store.begin(TENANT, newer) == Started()
    store.complete(TENANT, request(), CREATED)
    store.abandon(TENANT, request())
    assert store.begin(TENANT, newer) == InFlight()


def test_abandon_releases_only_an_unrecorded_claim(store: MemoryIdempotencyStore) -> None:
    store.begin(TENANT, request())
    store.abandon(TENANT, request())
    assert store.begin(TENANT, request()) == Started()
    store.complete(TENANT, request(), CREATED)
    store.abandon(TENANT, request())
    assert store.begin(TENANT, request()) == Replay(CREATED)
    store.abandon(OTHER_TENANT, request())
    store.complete(OTHER_TENANT, request(), CREATED)
    assert len(store) == 1


def test_the_purge_deletes_what_expired(store: MemoryIdempotencyStore, clock: Clock) -> None:
    store.begin(TENANT, request())
    store.complete(TENANT, request(), CREATED)
    store.begin(OTHER_TENANT, request())
    store.begin(TENANT, request(key="a-second-key"))
    assert store.purge_expired() == 0
    clock.now += IN_FLIGHT_LEASE + timedelta(seconds=1)
    assert store.purge_expired() == 2
    clock.now += REPLAY_WINDOW
    assert store.purge_expired() == 1
    assert len(store) == 0


# ---- the errors -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "slug", "status"),
    [
        (IdempotencyKeyRequiredError, "idempotency-key-required", 428),
        (IdempotencyKeyReusedError, "idempotency-key-reused", 422),
        (IdempotencyRequestInFlightError, "idempotency-request-in-flight", 409),
    ],
)
def test_every_service_maps_the_idempotency_problems(
    error: type[IdempotencyKeyRequiredError], slug: str, status: int
) -> None:
    assert error.type_slug == slug
    assert DEFAULT_STATUS_BY_ERROR[error] == status
    assert error().detail != error.title


def test_the_package_loads_neither_fastapi_nor_sqlalchemy() -> None:
    code = (
        "import sys, py_common.idempotency, py_common.idempotency.errors;"
        "loaded = [m for m in sys.modules if m.split('.')[0] in "
        "('fastapi', 'starlette', 'sqlalchemy', 'alembic')];"
        "print(loaded); sys.exit(1 if loaded else 0)"
    )
    finished = subprocess.run([sys.executable, "-c", code], capture_output=True, check=False)
    assert finished.returncode == 0, finished.stdout


def test_the_purge_command_needs_a_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        purge_main([])
    assert stopped.value.code == 2
    assert "purge" in capsys.readouterr().err


# ---- through a route --------------------------------------------------------------------------


class ThingIn(BaseModel):
    name: str


class ThingOut(BaseModel):
    id: int
    name: str


@dataclass
class Service:
    store: MemoryIdempotencyStore
    calls: list[str] = field(default_factory=list)
    reply: Callable[[ThingIn], ThingOut | JSONResponse] | None = None

    def make(self, body: ThingIn) -> ThingOut | JSONResponse:
        self.calls.append(body.name)
        if self.reply is not None:
            return self.reply(body)
        return ThingOut(id=len(self.calls), name=body.name)


def _app(service: Service) -> FastAPI:
    router = APIRouter(prefix="/t")

    @router.post(
        "/things",
        status_code=201,
        response_model=ThingOut,
        responses=IDEMPOTENCY_RESPONSES,
    )
    def create(body: ThingIn, key: IdempotencyKey) -> JSONResponse:
        return run_idempotent(service.store, TENANT, key, 201, lambda: service.make(body))

    return create_app(service_name="t", version="0", routers=[router])


@pytest.fixture
def service(store: MemoryIdempotencyStore) -> Service:
    return Service(store)


@pytest.fixture
def client(service: Service) -> Iterator[TestClient]:
    with TestClient(_app(service), raise_server_exceptions=False) as test_client:
        yield test_client


def problem_type(response: Any) -> str:
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    kind: str = response.json()["type"]
    return kind.removeprefix(PROBLEM_TYPE_PREFIX)


def test_a_retry_gets_the_first_response_marked_as_replayed(
    client: TestClient, service: Service
) -> None:
    first = client.post(PATH, json={"name": "a"}, headers={IDEMPOTENCY_KEY_HEADER: KEY})
    again = client.post(PATH, json={"name": "a"}, headers={IDEMPOTENCY_KEY_HEADER: KEY})
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json() == {"id": 1, "name": "a"}
    assert REPLAYED_HEADER.lower() not in first.headers
    assert again.headers[REPLAYED_HEADER] == "true"
    assert service.calls == ["a"]


def test_a_request_without_a_key_is_428(client: TestClient, service: Service) -> None:
    response = client.post(PATH, json={"name": "a"})
    assert response.status_code == 428
    assert problem_type(response) == "idempotency-key-required"
    assert service.calls == []


@pytest.mark.parametrize("key", ["short", "k" * 129, "has spaces in it"])
def test_a_malformed_key_is_a_request_error(client: TestClient, key: str) -> None:
    response = client.post(PATH, json={"name": "a"}, headers={IDEMPOTENCY_KEY_HEADER: key})
    assert response.status_code == 422
    assert problem_type(response) == "request-invalid"


def test_the_same_key_with_another_body_is_422(client: TestClient, service: Service) -> None:
    client.post(PATH, json={"name": "a"}, headers={IDEMPOTENCY_KEY_HEADER: KEY})
    response = client.post(PATH, json={"name": "b"}, headers={IDEMPOTENCY_KEY_HEADER: KEY})
    assert response.status_code == 422
    assert problem_type(response) == "idempotency-key-reused"
    assert service.calls == ["a"]


def test_a_retry_while_the_first_request_runs_is_409(client: TestClient, service: Service) -> None:
    body = b'{"name":"a"}'
    service.store.begin(TENANT, IdempotencyRequest.of(KEY, "POST", PATH, body))
    response = client.post(
        PATH,
        content=body,
        headers={IDEMPOTENCY_KEY_HEADER: KEY, "content-type": "application/json"},
    )
    assert response.status_code == 409
    assert problem_type(response) == "idempotency-request-in-flight"
    assert response.headers["retry-after"] == "1"
    assert service.calls == []


def test_a_new_key_runs_again(client: TestClient, service: Service) -> None:
    client.post(PATH, json={"name": "a"}, headers={IDEMPOTENCY_KEY_HEADER: KEY})
    response = client.post(
        PATH, json={"name": "a"}, headers={IDEMPOTENCY_KEY_HEADER: "another-key"}
    )
    assert response.json() == {"id": 2, "name": "a"}
    assert service.calls == ["a", "a"]


def test_a_5xx_is_never_recorded(client: TestClient, service: Service) -> None:
    service.reply = lambda body: JSONResponse({"detail": "later"}, status_code=503)
    first = client.post(PATH, json={"name": "a"}, headers={IDEMPOTENCY_KEY_HEADER: KEY})
    assert first.status_code == 503
    service.reply = None
    again = client.post(PATH, json={"name": "a"}, headers={IDEMPOTENCY_KEY_HEADER: KEY})
    assert again.status_code == 201
    assert REPLAYED_HEADER.lower() not in again.headers
    assert service.calls == ["a", "a"]


def test_an_exception_releases_the_key(client: TestClient, service: Service) -> None:
    def fail(body: ThingIn) -> ThingOut:
        raise RuntimeError("the database went away")

    service.reply = fail
    first = client.post(PATH, json={"name": "a"}, headers={IDEMPOTENCY_KEY_HEADER: KEY})
    assert first.status_code == 500
    service.reply = None
    again = client.post(PATH, json={"name": "a"}, headers={IDEMPOTENCY_KEY_HEADER: KEY})
    assert again.status_code == 201
    assert service.calls == ["a", "a"]


def test_a_4xx_response_and_its_headers_are_replayed(client: TestClient, service: Service) -> None:
    service.reply = lambda body: JSONResponse(
        {"detail": "taken"}, status_code=409, headers={"Location": "/t/things/1"}
    )
    first = client.post(PATH, json={"name": "a"}, headers={IDEMPOTENCY_KEY_HEADER: KEY})
    service.reply = None
    again = client.post(PATH, json={"name": "a"}, headers={IDEMPOTENCY_KEY_HEADER: KEY})
    assert first.status_code == again.status_code == 409
    assert again.json() == {"detail": "taken"}
    assert again.headers["location"] == "/t/things/1"
    assert again.headers[REPLAYED_HEADER] == "true"
    assert service.calls == ["a"]


def test_the_spec_documents_the_header_and_the_problems() -> None:
    spec = _app(Service(MemoryIdempotencyStore())).openapi()
    operation = spec["paths"][PATH]["post"]
    header = next(p for p in operation["parameters"] if p["name"] == IDEMPOTENCY_KEY_HEADER)
    assert header["in"] == "header"
    assert header["required"] is False
    schema = header["schema"]["anyOf"][0]
    assert (schema["minLength"], schema["maxLength"]) == (8, 128)
    assert {"201", "409", "422", "428"} <= set(operation["responses"])


# ---- with a recorder in the caller's transaction ------------------------------------------


@dataclass
class Recorder:
    """Stands in for a recorder bound to a transaction: remembers what it was asked."""

    outcome: Outcome = field(default_factory=Started)
    calls: list[str] = field(default_factory=list)

    def begin(self, tenant: TenantId, request: IdempotencyRequest) -> Outcome:
        self.calls.append("begin")
        return self.outcome

    def complete(
        self, tenant: TenantId, request: IdempotencyRequest, response: StoredResponse
    ) -> None:
        self.calls.append(f"complete {response.status_code}")

    def abandon(self, tenant: TenantId, request: IdempotencyRequest) -> None:
        self.calls.append("abandon")


def test_with_a_recorder_the_store_is_not_touched(store: MemoryIdempotencyStore) -> None:
    recorder = Recorder()
    response = run_idempotent(
        store, TENANT, request(), 201, lambda: ThingOut(id=1, name="a"), recorder=recorder
    )
    assert response.status_code == 201
    assert recorder.calls == ["begin", "complete 201"]
    assert len(store) == 0


def test_with_a_recorder_a_failure_is_left_to_the_callers_rollback(
    store: MemoryIdempotencyStore,
) -> None:
    recorder = Recorder()

    def fail() -> ThingOut:
        raise IdempotencyKeyReusedError("stands in for any error")

    with pytest.raises(IdempotencyKeyReusedError):
        run_idempotent(store, TENANT, request(), 201, fail, recorder=recorder)
    assert recorder.calls == ["begin"]


def test_with_a_recorder_a_5xx_releases_the_key_in_the_transaction(
    store: MemoryIdempotencyStore,
) -> None:
    recorder = Recorder()
    response = run_idempotent(
        store,
        TENANT,
        request(),
        201,
        lambda: JSONResponse({"detail": "later"}, status_code=502),
        recorder=recorder,
    )
    assert response.status_code == 502
    assert recorder.calls == ["begin", "abandon"]


@pytest.mark.parametrize(
    ("outcome", "error"),
    [(Reused(), IdempotencyKeyReusedError), (InFlight(), IdempotencyRequestInFlightError)],
)
def test_a_recorder_that_refuses_never_runs_the_work(
    store: MemoryIdempotencyStore, outcome: Outcome, error: type[Exception]
) -> None:
    recorder = Recorder(outcome=outcome)
    with pytest.raises(error):
        run_idempotent(store, TENANT, request(), 201, pytest.fail, recorder=recorder)


def test_a_recorder_replays_what_it_recorded(store: MemoryIdempotencyStore) -> None:
    recorder = Recorder(outcome=Replay(CREATED))
    response = run_idempotent(store, TENANT, request(), 201, pytest.fail, recorder=recorder)
    assert response.status_code == 201
    assert bytes(response.body) == b'{"id":7}'
    assert response.headers[REPLAYED_HEADER] == "true"
    assert response.headers["location"] == "/t/things/7"


def test_a_failed_release_does_not_hide_the_original_error() -> None:
    class Broken(MemoryIdempotencyStore):
        def abandon(self, tenant: TenantId, request: IdempotencyRequest) -> None:
            raise OSError("connection reset")

    def fail() -> ThingOut:
        raise RuntimeError("the work failed")

    with pytest.raises(RuntimeError, match="the work failed"):
        run_idempotent(Broken(), TENANT, request(), 201, fail)
