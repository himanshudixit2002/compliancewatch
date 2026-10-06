"""Who may talk to the helper: the token on every API request, the exact Host and Origin, no
CORS, bounded JSON bodies, single-use tickets for an EventSource, single-use launch codes that a
window swaps for the token, and static files from ui/ only.
"""

import concurrent.futures
import re
from collections.abc import Iterator
from pathlib import Path

import panel_server as server
import pytest
from serverkit import Served


@pytest.fixture
def ui(tmp_path: Path) -> Path:
    folder = tmp_path / "ui"
    (folder / "views").mkdir(parents=True)
    (folder / "index.html").write_text("<!doctype html><title>x</title>")
    (folder / "app.js").write_text("export {};\n")
    (folder / "views" / "home.js").write_text("export {};\n")
    (folder / ".secret.js").write_text("hidden")
    (folder / "notes.md").write_text("no type for this")
    (tmp_path / "outside.js").write_text("outside")
    return folder


@pytest.fixture
def served(ui: Path) -> Iterator[Served]:
    with Served(ui_dir=ui) as running:
        yield running


def test_every_api_request_needs_the_token(served: Served) -> None:
    for path in ("/api/status", "/api/actions", "/api/meta", "/api/events"):
        missing = served.get(path, token=None)
        assert missing.status == 401
        assert missing.error["code"] == "unauthorized"
        wrong = served.get(path, token="not-the-token")
        assert wrong.status == 401
    refused = served.post("/api/actions/backup/run", {"params": {}}, token="nope")
    assert refused.status == 401
    assert served.app.runs.recent(5) == []
    assert served.get("/api/status").status == 200


def test_the_host_must_be_the_helper_s_own(served: Served) -> None:
    for host in (f"localhost:{served.port}", "evil.example", f"127.0.0.1:{served.port + 1}"):
        api = served.get("/api/status", headers={"Host": host})
        assert api.status == 403
        assert api.error["code"] == "bad-host"
        page = served.get("/", token=None, headers={"Host": host})
        assert page.status == 403


def test_a_foreign_origin_or_site_is_refused(served: Served) -> None:
    for origin in ("http://evil.example", "null", f"http://localhost:{served.port}"):
        reply = served.get("/api/status", headers={"Origin": origin})
        assert reply.status == 403
        assert reply.error["code"] == "bad-origin"
    cross = served.get("/api/status", headers={"Sec-Fetch-Site": "cross-site"})
    assert cross.status == 403
    same = served.get(
        "/api/status",
        headers={"Origin": f"http://127.0.0.1:{served.port}", "Sec-Fetch-Site": "same-origin"},
    )
    assert same.status == 200


def test_there_is_no_cors(served: Served) -> None:
    preflight = served.request(
        "OPTIONS",
        "/api/status",
        headers={
            "Origin": f"http://127.0.0.1:{served.port}",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert preflight.status == 405
    for reply in (preflight, served.get("/api/status"), served.get("/", token=None)):
        assert not [key for key in reply.headers if key.startswith("access-control-")]
        assert reply.headers["cache-control"] == "no-store"


def test_bodies_are_bounded_json_objects(served: Served) -> None:
    path = "/api/actions/backup/preview"
    big = served.request(
        "POST",
        path,
        raw=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": str(server.MAX_BODY + 1)},
    )
    assert big.status == 413
    assert big.error["code"] == "too-large"
    form = served.request(
        "POST", path, raw=b"a=b", headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert form.status == 415
    chunked = served.request(
        "POST",
        path,
        raw=b"2\r\n{}\r\n0\r\n\r\n",
        headers={"Content-Type": "application/json", "Transfer-Encoding": "chunked"},
    )
    assert chunked.status == 411
    broken = served.request(
        "POST", path, raw=b"{nope", headers={"Content-Type": "application/json"}
    )
    assert broken.status == 400
    assert broken.error["code"] == "bad-json"
    listed = served.request("POST", path, raw=b"[1]", headers={"Content-Type": "application/json"})
    assert listed.status == 400
    assert served.request("POST", path).status == 200  # no body at all is fine
    assert served.request("DELETE", "/api/prefs").status == 405


def test_a_ticket_opens_the_event_stream_once_and_nothing_else(served: Served) -> None:
    issued = served.post("/api/events/ticket").json
    assert issued["expires_in"] == int(server.TICKET_SECONDS)
    ticket = issued["ticket"]
    stream = served.events(ticket=ticket)
    assert stream.response.status == 200
    assert stream.next().name == "hello"
    stream.close()
    again = served.events(ticket=ticket)
    assert again.response.status == 401
    other = served.post("/api/events/ticket").json["ticket"]
    elsewhere = served.get(f"/api/status?ticket={other}", token=None)
    assert elsewhere.status == 401
    assert served.events(ticket="t-made-up").response.status == 401


def test_tickets_and_confirm_tokens_expire_and_work_once() -> None:
    now = [100.0]
    book = server.Book("c-", 120, lambda: now[0])
    token = book.issue("backup:{}", {"pids": [1]})
    assert book.take(token, "restore:{}") is None  # bound to its action and parameters
    token = book.issue("backup:{}", {"pids": [1]})
    assert book.take(token, "backup:{}") == {"pids": [1]}
    assert book.take(token, "backup:{}") is None
    late = book.issue("backup:{}")
    now[0] += 121
    assert book.take(late, "backup:{}") is None
    assert book.take("t-other-prefix", "") is None
    assert book.take(None, "") is None


def own_origin(served: Served) -> dict[str, str]:
    return {"Origin": f"http://127.0.0.1:{served.port}"}


def test_a_launch_code_is_swapped_for_the_token_once(served: Served) -> None:
    issued = served.post("/api/launch-code")
    assert issued.status == 200
    code = issued.json["code"]
    assert re.fullmatch(r"l-[\w-]{20,}", code)
    assert issued.json["expires_in"] == 30
    swapped = served.post("/api/launch", {"code": code}, token=None, headers=own_origin(served))
    assert swapped.status == 200
    assert swapped.json == {"token": served.token}
    assert swapped.headers["cache-control"] == "no-store"
    again = served.post("/api/launch", {"code": code}, token=None, headers=own_origin(served))
    assert again.status == 401
    assert again.error["code"] == "launch-expired"
    for made_up in ("l-made-up", served.token, "", None):
        reply = served.post(
            "/api/launch", {"code": made_up}, token=None, headers=own_origin(served)
        )
        assert reply.status == 401


def test_a_launch_code_expires_after_30_seconds(served: Served) -> None:
    now = [1000.0]
    served.app.launches = server.Book("l-", server.LAUNCH_SECONDS, lambda: now[0])
    late = served.post("/api/launch-code").json["code"]
    now[0] += server.LAUNCH_SECONDS + 1
    reply = served.post("/api/launch", {"code": late}, token=None, headers=own_origin(served))
    assert reply.status == 401
    assert reply.error["code"] == "launch-expired"
    in_time = served.post("/api/launch-code").json["code"]
    now[0] += server.LAUNCH_SECONDS - 1
    reply = served.post("/api/launch", {"code": in_time}, token=None, headers=own_origin(served))
    assert reply.json == {"token": served.token}


def test_only_the_helper_s_own_page_may_swap_a_launch_code(served: Served) -> None:
    assert served.post("/api/launch-code", token=None).status == 401
    assert served.post("/api/launch-code", token="not-the-token").status == 401
    code = served.post("/api/launch-code").json["code"]
    for headers in (
        {},
        {"Origin": "http://evil.example"},
        {"Origin": "null"},
        {"Origin": f"http://localhost:{served.port}"},
        {**own_origin(served), "Sec-Fetch-Site": "cross-site"},
    ):
        refused = served.post("/api/launch", {"code": code}, token=None, headers=headers)
        assert refused.status == 403, headers
        assert refused.error["code"] == "bad-origin"
    wrong_host = served.post(
        "/api/launch",
        {"code": code},
        token=None,
        headers={**own_origin(served), "Host": f"localhost:{served.port}"},
    )
    assert wrong_host.status == 403
    assert served.get("/api/launch", token=None).status == 405
    # a refused swap leaves the code for the window it was made for
    reply = served.post("/api/launch", {"code": code}, token=None, headers=own_origin(served))
    assert reply.json == {"token": served.token}


def test_the_address_a_window_opens_with_carries_no_token(served: Served) -> None:
    url = served.app.launch_url("processes")
    assert served.token not in url
    found = re.fullmatch(
        rf"http://127\.0\.0\.1:{served.port}/#launch=(l-[\w-]+)&view=processes", url
    )
    assert found
    reply = served.post(
        "/api/launch", {"code": found.group(1)}, token=None, headers=own_origin(served)
    )
    assert reply.json == {"token": served.token}


def test_static_files_come_from_ui_only(served: Served, ui: Path) -> None:
    index = served.get("/", token=None)
    assert index.status == 200
    assert index.headers["content-type"] == "text/html; charset=utf-8"
    assert index.headers["content-security-policy"] == server.CSP
    assert "style-src 'self';" in server.CSP
    assert index.headers["x-content-type-options"] == "nosniff"
    assert index.headers["referrer-policy"] == "no-referrer"
    script = served.get("/views/home.js", token=None)
    assert script.status == 200
    assert script.headers["content-type"] == "text/javascript; charset=utf-8"
    assert "content-security-policy" not in script.headers
    assert served.get("/?r=2", token=None).status == 200
    for path in (
        "/../outside.js",
        "/%2e%2e/outside.js",
        "/views/../../outside.js",
        "/.secret.js",
        "/notes.md",
        "/nothing.js",
        "//etc/passwd",
        "/views/",
    ):
        assert served.get(path, token=None).status == 404, path
    assert served.request("POST", "/index.html", token=None).status == 405


def test_the_token_is_never_logged(served: Served, capsys: pytest.CaptureFixture[str]) -> None:
    served.get("/api/status")
    served.get("/api/status", token=None)
    served.get(f"/api/events?ticket={served.token}", token=None)
    served.post("/api/actions/nope/run", {"params": {}})
    captured = capsys.readouterr()
    assert served.token not in captured.err
    assert served.token not in captured.out


def test_the_window_s_files_load_all_at_once(served: Served) -> None:
    paths = ["/", "/app.js", "/views/home.js"] * 16
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(paths)) as pool:
        statuses = list(pool.map(lambda path: served.get(path, token=None).status, paths))
    assert statuses == [200] * len(paths)
    assert served.server.request_queue_size >= 64
