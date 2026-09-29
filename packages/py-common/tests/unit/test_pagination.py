"""Keyset pagination: the cursor round trip, the cursors a list refuses, the page parameters and
the page body on a real route."""

import base64
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ConfigDict

from domain_kernel.errors import PROBLEM_TYPE_PREFIX
from py_common.app import create_app
from py_common.pagination import (
    CURSOR_VERSION,
    DEFAULT_LIMIT,
    MAX_CURSOR_CHARS,
    MAX_LIMIT,
    InvalidCursorError,
    Page,
    PageParams,
    Pagination,
    decode_cursor,
    encode_cursor,
    page_of,
)
from py_common.problems import DEFAULT_STATUS_BY_ERROR, PROBLEM_MEDIA_TYPE

SCOPE = "test.things"
INVALID = PROBLEM_TYPE_PREFIX + "pagination-cursor-invalid"


class ThingKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    id: UUID


class DatedKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    due_at: datetime
    number: int


class Thing(BaseModel):
    name: str
    id: UUID


THINGS = [Thing(name=f"thing {number:03d}", id=UUID(int=number)) for number in range(1, 8)]


def _key(thing: Thing) -> ThingKey:
    return ThingKey(name=thing.name, id=thing.id)


def _raw(payload: object) -> str:
    text = json.dumps(payload)
    return base64.urlsafe_b64encode(text.encode()).rstrip(b"=").decode()


# ---- the cursor ---------------------------------------------------------------------------------


def test_a_cursor_round_trips_its_keyset() -> None:
    key = ThingKey(name="Acme Traders", id=UUID(int=5))
    cursor = encode_cursor(SCOPE, key)
    assert decode_cursor(cursor, SCOPE, ThingKey) == key
    dated = DatedKey(due_at=datetime(2026, 4, 20, 18, 29, 59, tzinfo=UTC), number=3)
    assert decode_cursor(encode_cursor("test.dated", dated), "test.dated", DatedKey) == dated


def test_a_cursor_is_versioned_base64url_json_without_padding() -> None:
    cursor = encode_cursor(SCOPE, ThingKey(name="a?b/c", id=UUID(int=1)))
    assert "=" not in cursor
    assert set(cursor) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    assert decoded == {
        "k": {"id": str(UUID(int=1)), "name": "a?b/c"},
        "s": SCOPE,
        "v": CURSOR_VERSION,
    }


@given(name=st.text(max_size=40), number=st.integers(min_value=0, max_value=2**128 - 1))
def test_any_short_text_key_round_trips(name: str, number: int) -> None:
    key = ThingKey(name=name, id=UUID(int=number))
    assert decode_cursor(encode_cursor(SCOPE, key), SCOPE, ThingKey) == key


def test_a_lone_surrogate_in_a_text_key_round_trips() -> None:
    key = ThingKey(name="\ud800 half a pair", id=UUID(int=2))
    assert decode_cursor(encode_cursor(SCOPE, key), SCOPE, ThingKey) == key


def test_a_keyset_too_long_for_a_cursor_is_refused_when_encoding() -> None:
    with pytest.raises(ValueError, match="at most 512 fit"):
        encode_cursor(SCOPE, ThingKey(name="x" * 400, id=UUID(int=1)))
    with pytest.raises(ValueError, match="name of its list"):
        encode_cursor("", ThingKey(name="x", id=UUID(int=1)))


def test_a_cursor_of_another_list_is_refused() -> None:
    cursor = encode_cursor("test.other", ThingKey(name="a", id=UUID(int=1)))
    with pytest.raises(InvalidCursorError, match="another list"):
        decode_cursor(cursor, SCOPE, ThingKey)


@pytest.mark.parametrize(
    ("cursor", "reason"),
    [
        ("not a cursor", "base64url"),
        ("a" * (MAX_CURSOR_CHARS + 1), "base64url"),
        ("abcde", "decode to JSON"),
        (base64.urlsafe_b64encode(b"\xff\xfe").decode().rstrip("="), "decode to JSON"),
        (_raw("text")[:-2] + "__", "decode to JSON"),
        (_raw(["k", "s", "v"]), "issued"),
        (_raw({"k": {}, "s": SCOPE}), "issued"),
        (_raw({"k": {}, "s": SCOPE, "v": 1, "x": 1}), "issued"),
        (_raw({"k": {}, "s": SCOPE, "v": 2}), "version"),
        (_raw({"k": {}, "s": SCOPE, "v": True}), "version"),
        (_raw({"k": {}, "s": SCOPE, "v": "1"}), "version"),
        (_raw({"k": {"name": "a", "id": "not-a-uuid"}, "s": SCOPE, "v": 1}), "keyset"),
        (_raw({"k": {"name": "a"}, "s": SCOPE, "v": 1}), "keyset"),
        (_raw({"k": ["a", str(UUID(int=1))], "s": SCOPE, "v": 1}), "keyset"),
        (_raw({"k": {"name": "a", "id": str(UUID(int=1)), "x": 1}, "s": SCOPE, "v": 1}), "keyset"),
    ],
)
def test_a_tampered_cursor_is_refused(cursor: str, reason: str) -> None:
    with pytest.raises(InvalidCursorError, match=reason):
        decode_cursor(cursor, SCOPE, ThingKey)


def test_json_constants_are_not_json() -> None:
    cursor = base64.urlsafe_b64encode(b'{"k":NaN,"s":"test.things","v":1}').decode()
    with pytest.raises(InvalidCursorError, match="decode to JSON"):
        decode_cursor(cursor.rstrip("="), SCOPE, ThingKey)


def test_an_edited_character_is_refused_or_still_reads_as_a_keyset_of_this_list() -> None:
    cursor = encode_cursor(SCOPE, ThingKey(name="Acme", id=UUID(int=9)))
    for index in range(len(cursor)):
        edited = cursor[:index] + ("A" if cursor[index] != "A" else "B") + cursor[index + 1 :]
        try:
            found = decode_cursor(edited, SCOPE, ThingKey)
        except InvalidCursorError:
            continue
        # A cursor that is still well formed only moves where the page starts.
        assert isinstance(found, ThingKey)


def test_the_cursor_error_is_a_422_problem_by_default() -> None:
    error = InvalidCursorError()
    assert (error.type_slug, error.title) == (
        "pagination-cursor-invalid",
        "Pagination cursor is invalid",
    )
    assert DEFAULT_STATUS_BY_ERROR[InvalidCursorError] == 422


# ---- a page -------------------------------------------------------------------------------------


def test_page_of_keeps_limit_rows_and_points_after_the_last_one() -> None:
    rows, cursor = page_of(THINGS[:4], 3, SCOPE, _key)
    assert rows == THINGS[:3]
    assert cursor is not None
    assert decode_cursor(cursor, SCOPE, ThingKey) == _key(THINGS[2])


def test_page_of_the_last_page_has_no_cursor() -> None:
    assert page_of(THINGS[:3], 3, SCOPE, _key) == (THINGS[:3], None)
    assert page_of([], 3, SCOPE, _key) == ([], None)
    with pytest.raises(ValueError, match="at least 1"):
        page_of(THINGS, 0, SCOPE, _key)


def test_page_params_decode_the_keyset() -> None:
    assert PageParams().limit == DEFAULT_LIMIT
    assert PageParams().after(SCOPE, ThingKey) is None
    cursor = encode_cursor(SCOPE, _key(THINGS[0]))
    assert PageParams(limit=2, cursor=cursor).after(SCOPE, ThingKey) == _key(THINGS[0])


# ---- on a route ---------------------------------------------------------------------------------


def _app() -> FastAPI:
    router = APIRouter(prefix="/t")

    @router.get("/things")
    def things(page: Pagination) -> Page[Thing]:
        after = page.after(SCOPE, ThingKey)
        remaining = [
            thing
            for thing in THINGS
            if after is None or (thing.name, thing.id) > (after.name, after.id)
        ]
        rows, next_cursor = page_of(remaining[: page.limit + 1], page.limit, SCOPE, _key)
        return Page[Thing](items=rows, next_cursor=next_cursor)

    return create_app(service_name="t", version="0", routers=[router])


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(_app()) as test_client:
        yield test_client


def test_a_list_is_read_page_by_page(client: TestClient) -> None:
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"limit": 3}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get("/t/things", params=params)
        assert response.status_code == 200
        body = response.json()
        seen.extend(item["name"] for item in body["items"])
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == [thing.name for thing in THINGS]
    assert pages == 3


def test_the_default_limit_is_50(client: TestClient) -> None:
    body = client.get("/t/things").json()
    assert len(body["items"]) == len(THINGS)
    assert body["next_cursor"] is None


@pytest.mark.parametrize("cursor", ["garbage!", _raw({"k": {}, "s": SCOPE, "v": 1})])
def test_a_tampered_cursor_is_a_422_problem(client: TestClient, cursor: str) -> None:
    response = client.get("/t/things", params={"cursor": cursor})
    assert response.status_code == 422
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json()["type"] == INVALID
    assert response.json()["title"] == "Pagination cursor is invalid"


def test_a_foreign_cursor_is_a_422_problem(client: TestClient) -> None:
    foreign = encode_cursor("test.other", _key(THINGS[0]))
    response = client.get("/t/things", params={"cursor": foreign})
    assert response.status_code == 422
    assert response.json()["type"] == INVALID


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": MAX_LIMIT + 1},
        {"cursor": ""},
        {"cursor": "a" * (MAX_CURSOR_CHARS + 1)},
    ],
)
def test_limits_outside_the_bounds_are_request_errors(
    client: TestClient, params: dict[str, str | int]
) -> None:
    response = client.get("/t/things", params=params)
    assert response.status_code == 422
    assert response.json()["type"] == PROBLEM_TYPE_PREFIX + "request-invalid"


def test_the_spec_documents_limit_cursor_and_the_page() -> None:
    spec = _app().openapi()
    operation = spec["paths"]["/t/things"]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    assert parameters["limit"]["in"] == "query"
    assert parameters["limit"]["schema"]["maximum"] == MAX_LIMIT
    assert parameters["limit"]["schema"]["minimum"] == 1
    assert parameters["limit"]["schema"]["default"] == DEFAULT_LIMIT
    cursor_schema = parameters["cursor"]["schema"]["anyOf"][0]
    assert cursor_schema["maxLength"] == MAX_CURSOR_CHARS
    page = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    schema = spec["components"]["schemas"][page.rsplit("/", 1)[1]]
    assert set(schema["required"]) == {"items", "next_cursor"}
