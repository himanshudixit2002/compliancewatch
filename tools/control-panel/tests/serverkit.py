"""The helper on a free port for the tests, with a small client for its API and event stream.

``Served`` runs panel_server's HTTP layer and App over a core (the demo one unless given) on
127.0.0.1, with the shared poller, and stops it after. Nothing here starts a real program.
"""

from __future__ import annotations

import http.client
import json
import socket
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

import panel_demo
import panel_server as server


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    text: str

    @property
    def json(self) -> Any:
        return json.loads(self.text)

    @property
    def error(self) -> dict[str, Any]:
        body = self.json
        assert set(body) == {"error"}, body
        assert set(body["error"]) == {"code", "message", "detail", "fix", "action"}, body
        return dict(body["error"])


@dataclass
class Event:
    id: int | None
    name: str
    data: Any


@dataclass
class Stream:
    """An open ``GET /api/events``: its frames, read as they come."""

    connection: http.client.HTTPConnection
    sock: socket.socket
    response: http.client.HTTPResponse
    retry: int | None = None
    comments: list[str] = field(default_factory=list)

    def next(self, timeout: float = 10.0) -> Event:
        """The next event (comments and ``retry`` noted on the way)."""
        sock = self.sock
        deadline = time.monotonic() + timeout
        event_id: int | None = None
        name = "message"
        data: list[str] = []
        while True:
            sock.settimeout(max(deadline - time.monotonic(), 0.01))
            raw = self.response.readline()
            if not raw:
                raise EOFError("the stream ended")
            line = raw.decode("utf-8").rstrip("\n")
            if line == "":
                if data:
                    return Event(event_id, name, json.loads("\n".join(data)))
                continue
            if line.startswith(":"):
                self.comments.append(line)
                continue
            key, _, value = line.partition(": ")
            if key == "retry":
                self.retry = int(value)
            elif key == "id":
                event_id = int(value)
            elif key == "event":
                name = value
            elif key == "data":
                data.append(value)

    def until(self, name: str, timeout: float = 10.0) -> Event:
        deadline = time.monotonic() + timeout
        while True:
            event = self.next(max(deadline - time.monotonic(), 0.01))
            if event.name == name:
                return event

    def close(self) -> None:
        self.response.close()
        self.connection.close()
        self.sock.close()


class Served:
    """The helper over ``backend``, listening on a free port while the ``with`` block runs."""

    def __init__(
        self,
        backend: server.Backend | None = None,
        *,
        ui_dir: Path | None = None,
        idle_seconds: float = server.IDLE_EXIT_SECONDS,
    ) -> None:
        self.backend = backend if backend is not None else panel_demo.DemoBackend(pace=0.01)
        self.server = server.make_server(
            self.backend,
            prefs=server.Prefs(None),
            ui_dir=ui_dir if ui_dir is not None else server.UI_DIR,
            idle_seconds=idle_seconds,
        )
        self.app = self.server.app
        self.port = self.app.port
        self.token = self.app.token
        self._serving = server.serving(self.server, poll_interval=0.02)
        self._streams: list[Stream] = []

    def __enter__(self) -> Served:
        self._serving.__enter__()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        for stream in self._streams:
            stream.close()
        self._serving.__exit__(kind, error, trace)

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self.port}"

    def request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        token: str | None = "",
        headers: Mapping[str, str] | None = None,
        raw: bytes | None = None,
    ) -> Reply:
        """One request. ``token``: "" sends the right one, None sends none, else that text."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        sent: dict[str, str] = {"Host": self.host}
        if token is not None:
            sent["X-Panel-Token"] = token or self.token
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            sent["Content-Type"] = "application/json"
        sent.update(headers or {})
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for key, value in sent.items():
            connection.putheader(key, value)
        if data is not None and "Content-Length" not in sent and "Transfer-Encoding" not in sent:
            connection.putheader("Content-Length", str(len(data)))
        connection.endheaders(data)
        response = connection.getresponse()
        text = response.read().decode("utf-8", "replace")
        reply = Reply(response.status, {k.lower(): v for k, v in response.getheaders()}, text)
        connection.close()
        return reply

    def get(self, path: str, **kwargs: Any) -> Reply:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, body: Mapping[str, Any] | None = None, **kwargs: Any) -> Reply:
        return self.request("POST", path, body if body is not None else {}, **kwargs)

    def events(
        self,
        *,
        last_id: int | None = None,
        ticket: str | None = None,
        token: str | None = "",
    ) -> Stream:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        path = "/api/events" + (f"?ticket={ticket}" if ticket else "")
        connection.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", self.host)
        connection.putheader("Accept", "text/event-stream")
        if token is not None and ticket is None:
            connection.putheader("X-Panel-Token", token or self.token)
        if last_id is not None:
            connection.putheader("Last-Event-ID", str(last_id))
        connection.endheaders()
        sock = connection.sock
        assert sock is not None
        response = connection.getresponse()
        stream = Stream(connection, sock, response)
        self._streams.append(stream)
        return stream

    def preview(self, action: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        reply = self.post(f"/api/actions/{action}/preview", {"params": dict(params or {})})
        assert reply.status == 200, reply.text
        return dict(reply.json)

    def start(self, action: str, params: Mapping[str, Any] | None = None) -> str:
        """Previews and runs ``action`` with its confirm token; the run's id."""
        preview = self.preview(action, params)
        body: dict[str, Any] = {"params": dict(params or {})}
        if preview["confirm_token"]:
            body["confirm_token"] = preview["confirm_token"]
        reply = self.post(f"/api/actions/{action}/run", body)
        assert reply.status == 202, reply.text
        return str(reply.json["run_id"])

    def finished(self, run_id: str, seconds: float = 20.0) -> dict[str, Any]:
        """The run once it has ended."""
        deadline = time.monotonic() + seconds
        while True:
            detail = self.get(f"/api/runs/{run_id}").json
            if detail["state"] != "running":
                return dict(detail)
            assert time.monotonic() < deadline, f"{run_id} still running: {detail}"
            time.sleep(0.05)

    def demo(self, body: Mapping[str, Any]) -> dict[str, Any]:
        reply = self.post("/api/demo/state", body)
        assert reply.status == 200, reply.text
        return dict(reply.json)


def wait_for(predicate: Callable[[], bool], seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)
