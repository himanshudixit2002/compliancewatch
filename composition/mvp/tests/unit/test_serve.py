"""The app process's listeners and server, and the settings behind them."""

import socket
from typing import Any

import pytest
import uvicorn
from pydantic import ValidationError

from cw_mvp import serve as serve_module
from cw_mvp.serve import listener, server
from cw_mvp.testing import mvp_settings


def test_an_ipv4_listener_binds_a_free_port() -> None:
    sock = listener("127.0.0.1", 0)
    try:
        assert sock.family == socket.AF_INET
        assert sock.getsockname()[1] > 0
    finally:
        sock.close()


def test_an_ipv6_listener_takes_ipv4_too() -> None:
    if not socket.has_ipv6:  # pragma: no cover - every CI runner has IPv6 sockets
        pytest.skip("no IPv6 sockets here")
    sock = listener("::", 0)
    try:
        assert sock.family == socket.AF_INET6
        assert sock.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY) == 0
    finally:
        sock.close()


def test_a_taken_port_closes_the_socket_it_made() -> None:
    taken = listener("127.0.0.1", 0)
    taken.listen()
    try:
        with pytest.raises(OSError, match="in use"):
            listener("127.0.0.1", _bound_port(taken))
    finally:
        taken.close()


def _bound_port(sock: socket.socket) -> int:
    port: int = sock.getsockname()[1]
    return port


def test_the_server_trusts_proxies_and_leaves_logging_to_py_common() -> None:
    settings = mvp_settings(mvp_forwarded_allow_ips="10.0.0.0/8")

    async def app(scope: Any, receive: Any, send: Any) -> None:  # pragma: no cover
        return None

    config = server(app, settings).config
    assert config.lifespan == "on"
    assert config.proxy_headers
    assert config.forwarded_allow_ips == "10.0.0.0/8"
    assert config.log_config is None
    assert not config.access_log


def test_serve_runs_one_server_on_the_public_and_the_internal_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[list[socket.socket]] = []
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, sockets: ran.append(sockets))
    monkeypatch.setattr(serve_module, "build_app", lambda settings: object())
    settings = mvp_settings(
        mvp_host="127.0.0.1", mvp_public_port=_free(), mvp_internal_port=_free()
    )
    serve_module.serve(settings)
    ((public, internal),) = ran
    try:
        assert public.getsockname()[1] == settings.mvp_public_port
        assert internal.getsockname()[1] == settings.mvp_internal_port
    finally:
        public.close()
        internal.close()


def _free() -> int:
    sock = listener("127.0.0.1", 0)
    try:
        return _bound_port(sock)
    finally:
        sock.close()


def test_the_listeners_need_two_ports() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        mvp_settings(mvp_public_port=9000, mvp_internal_port=9000)
