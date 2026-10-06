"""The event stream: its framing, the first events, ids and Last-Event-ID replay, the resync
when a client is too far behind, pings, and a slow client let go."""

import json
import time
from collections.abc import Iterator

import panel_server as server
import pytest
from serverkit import Served


@pytest.fixture
def served() -> Iterator[Served]:
    with Served() as running:
        yield running


def test_a_frame_is_an_id_a_name_and_one_line_of_json() -> None:
    hub = server.Hub()
    hub.publish("toast", {"title": "two\nlines", "body": "ünïcode"})
    _, replay = hub.subscribe(0)
    assert replay is not None
    frame = replay[0].frame().decode("utf-8")
    assert frame.endswith("\n\n")
    lines = frame[:-2].split("\n")
    assert lines[0] == "id: 1"
    assert lines[1] == "event: toast"
    assert lines[2].startswith("data: ")
    assert len(lines) == 3
    assert json.loads(lines[2][6:]) == {"title": "two\nlines", "body": "ünïcode"}
    assert server.frame("status", {"a": 1}) == b'event: status\ndata: {"a":1}\n\n'


def test_the_stream_starts_with_retry_hello_and_the_status(served: Served) -> None:
    stream = served.events()
    assert stream.response.status == 200
    assert stream.response.getheader("Content-Type") == "text/event-stream; charset=utf-8"
    assert stream.response.getheader("Cache-Control") == "no-store"
    hello = stream.next()
    assert stream.retry == 3000
    assert hello.name == "hello"
    assert hello.data == {"api": 1, "demo": True, "build": served.backend.build, "resync": False}
    status = stream.next()
    assert status.name == "status"
    assert "summary" in status.data


def test_events_carry_rising_ids_and_replay_after_last_event_id(served: Served) -> None:
    stream = served.events()
    stream.until("hello")
    served.app.hub.publish("toast", {"title": "one"})
    first = stream.until("toast")
    assert first.id is not None
    stream.close()
    for title in ("two", "three"):
        served.app.hub.publish("toast", {"title": title})
    again = served.events(last_id=first.id)
    hello = again.next()
    assert hello.data["resync"] is False
    replayed = [again.until("toast"), again.until("toast")]
    assert [event.data["title"] for event in replayed] == ["two", "three"]
    ids = [event.id for event in replayed]
    assert ids == sorted(ids)
    assert all(event_id is not None and event_id > first.id for event_id in ids)


def test_a_client_too_far_behind_is_told_to_fetch_everything(served: Served) -> None:
    stream = served.events()
    stream.until("hello")
    served.app.hub.publish("toast", {"title": "seen"})
    seen = stream.until("toast")
    stream.close()
    for index in range(server.EVENT_BUFFER + 5):
        served.app.hub.publish("toast", {"title": str(index)})
    late = served.events(last_id=seen.id)
    hello = late.next()
    assert hello.name == "hello"
    assert hello.data["resync"] is True
    assert late.next().name == "status"


def test_a_quiet_stream_pings(served: Served, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "PING_SECONDS", 0.1)
    stream = served.events()
    stream.until("status")
    time.sleep(0.5)
    served.app.hub.publish("toast", {"title": "after the pings"})
    stream.until("toast")
    assert ": ping" in stream.comments


def test_a_slow_client_is_let_go() -> None:
    hub = server.Hub()
    sub, _ = hub.subscribe(None)
    for index in range(server.CLIENT_QUEUE + 1):
        hub.publish("toast", {"n": index})
    assert sub.closed
    assert hub.count() == 0
