"""``cw-mvp serve``: the app process, one uvicorn server on two listeners.

Both listeners bind ``CW_MVP_HOST`` (``::``) with ``IPV6_V6ONLY`` off, so they take IPv4 and
IPv6 connections alike: Fly's private network is IPv6, the platform's health checks may be
IPv4. The public one (``CW_MVP_PUBLIC_PORT``, 8000) is what the edge reaches; the internal one
(``CW_MVP_INTERNAL_PORT``, 8080) is reachable only on the private network. Proxy headers are
trusted from ``CW_MVP_FORWARDED_ALLOW_IPS``. Logging is py-common's, so uvicorn's own
configuration and access log are off.

The process must stay one process: notification preferences, the gateway's response cache and
its budget-alarm markers are still held in memory.
"""

import socket
from collections.abc import Sequence

import uvicorn
from starlette.types import ASGIApp

from cw_mvp.app import build_app
from cw_mvp.settings import APP_SERVICE_NAME, MvpSettings

BACKLOG = 2048


def listener(host: str, port: int) -> socket.socket:
    """A bound TCP socket on ``host`` and ``port``; an IPv6 host also takes IPv4. Port 0 picks a
    free port, which ``getsockname()`` then gives."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if family == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    sock.set_inheritable(True)
    return sock


def server(app: ASGIApp, settings: MvpSettings) -> uvicorn.Server:
    """The uvicorn server of ``app``, before it binds anything."""
    config = uvicorn.Config(
        app,
        lifespan="on",
        proxy_headers=True,
        forwarded_allow_ips=settings.mvp_forwarded_allow_ips,
        log_config=None,
        access_log=False,
        backlog=BACKLOG,
    )
    return uvicorn.Server(config)


def serve(settings: MvpSettings | None = None) -> None:
    """Build the app and serve it on both listeners until SIGTERM or SIGINT."""
    settings = settings or MvpSettings(service_name=APP_SERVICE_NAME)
    sockets: Sequence[socket.socket] = (
        listener(settings.mvp_host, settings.mvp_public_port),
        listener(settings.mvp_host, settings.mvp_internal_port),
    )
    server(build_app(settings), settings).run(sockets=list(sockets))
