"""One ASGI app in front of every service: which app serves a request, and on which listener.

``ServiceDispatcher`` is pure ASGI. The lifespan and every path outside ``/v1/`` go to the root
app, which serves ``/health`` and ``/ready`` for the whole process. A ``/v1/`` path goes to the
service that owns it, with the scope unchanged (every service's routes carry its full prefix):

1. the facade paths of the public API, which sit outside any service's ``/v1/<name>`` prefix
   (``/v1/businesses`` belongs to profile), matched longest template first;
2. otherwise the first path segment, ``/v1/<name>``.

The table of both is built when the app starts from the routes each service actually serves
(``RouteTable.of``), so it cannot drift from them; ``tests/unit/test_dispatch.py`` holds its
facade paths and owners equal to the ``x-service`` of ``public.v1.json``.

The listener is the port the connection came in on, ``scope["server"]``: the internal port
serves every route, any other port is the public listener and serves a route only when
``cw_mvp.exposure`` says so. A path no service owns, and a route the public listener does not
serve, get a 404 ``route-not-found`` problem. While a service handles a request, the ``service``
log field names it. The routes the registry lists as calling other services over the internal
listener run at most ``limit`` at a time; the others wait their turn without holding a thread.
"""

import asyncio
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import structlog
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from starlette.requests import Request
from starlette.routing import compile_path
from starlette.types import ASGIApp, Receive, Scope, Send

from cw_mvp.errors import RouteNotFoundError
from cw_mvp.exposure import Exposure, served_publicly
from py_common.problems import problem_response
from py_common.settings import AuthMode

API_PREFIX: Final = "/v1/"
ROOT_PATHS: Final = frozenset({"/health", "/ready"})
"""The app's own paths; a hosted service's ``/health`` and ``/ready`` are never reached."""
_SAME_AS_GET: Final = "HEAD"


@dataclass(frozen=True, slots=True)
class RouteEntry:
    """One method of one route a service serves."""

    service: str
    method: str
    template: str
    regex: re.Pattern[str]
    exposure: Exposure | None = None
    loopback: bool = False

    @property
    def key(self) -> str:
        """``METHOD /path``, the form ``cw_mvp.exposure`` and the registry list routes in."""
        return f"{self.method} {self.template}"


def served_routes(app: FastAPI) -> Iterator[tuple[str, str]]:
    """``(method, template)`` for every route ``app`` serves, in the order it matches them,
    without FastAPI's docs pages, the probes every service has, and ``HEAD``, which a ``GET``
    route answers too."""
    skipped = {app.openapi_url, app.docs_url, app.redoc_url, app.swagger_ui_oauth2_redirect_url}
    skipped.update(ROOT_PATHS)
    for route in iter_route_contexts(app.routes):
        path = route.path
        if not path or path in skipped:
            continue
        for method in sorted(set(route.methods or ()) - {_SAME_AS_GET}):
            yield method, path


class RouteTable:
    """The routes of every service: who owns a path and which route serves a request."""

    def __init__(self, entries: Iterable[RouteEntry], prefixes: Mapping[str, str]) -> None:
        self._routes: dict[str, list[RouteEntry]] = {service: [] for service in prefixes}
        for entry in entries:
            self._routes[entry.service].append(entry)
        self._segments = {
            prefix.removeprefix(API_PREFIX): service for service, prefix in prefixes.items()
        }
        facade = [
            entry
            for entry in (entry for routes in self._routes.values() for entry in routes)
            if not _under(entry.template, prefixes[entry.service])
        ]
        self._facade = sorted(facade, key=lambda entry: len(entry.template), reverse=True)

    @classmethod
    def of(
        cls,
        apps: Mapping[str, FastAPI],
        prefixes: Mapping[str, str],
        *,
        exposure: Mapping[str, Mapping[str, Exposure]],
        loopback: Mapping[str, Iterable[str]],
    ) -> "RouteTable":
        """The table of what ``apps`` serve, each route with its class and whether it calls
        other services."""
        entries: list[RouteEntry] = []
        for service, app in apps.items():
            classes = exposure.get(service, {})
            calling = frozenset(loopback.get(service, ()))
            for method, template in served_routes(app):
                key = f"{method} {template}"
                entries.append(
                    RouteEntry(
                        service,
                        method,
                        template,
                        compile_path(template)[0],
                        exposure=classes.get(key),
                        loopback=key in calling,
                    )
                )
        return cls(entries, prefixes)

    def entries(self) -> Sequence[RouteEntry]:
        return [entry for routes in self._routes.values() for entry in routes]

    def facade(self) -> dict[str, str]:
        """Each facade path template and the service that owns it."""
        return {entry.template: entry.service for entry in self._facade}

    def owner(self, path: str) -> str | None:
        """The service that owns ``path``, or None."""
        if not path.startswith(API_PREFIX):
            return None
        for entry in self._facade:
            if entry.regex.match(path):
                return entry.service
        segment = path.removeprefix(API_PREFIX).split("/", 1)[0]
        return self._segments.get(segment)

    def route(self, service: str, method: str, path: str) -> RouteEntry | None:
        """The route of ``service`` that serves ``method`` on ``path``: the first that matches,
        as the service's own router picks it."""
        wanted = "GET" if method == _SAME_AS_GET else method
        for entry in self._routes.get(service, ()):
            if entry.method == wanted and entry.regex.match(path):
                return entry
        return None


def _under(template: str, prefix: str) -> bool:
    return template == prefix or template.startswith(prefix + "/")


class ServiceDispatcher:
    def __init__(
        self,
        root: ASGIApp,
        services: Mapping[str, ASGIApp],
        table: RouteTable,
        *,
        internal_port: int,
        auth_mode: AuthMode,
        loopback_limit: int,
    ) -> None:
        if loopback_limit < 1:
            raise ValueError("loopback_limit must be at least 1")
        self.root = root
        self.services = dict(services)
        self.table = table
        self.internal_port = internal_port
        self.auth_mode: AuthMode = auth_mode
        self.loopback_limit = loopback_limit
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loopback: asyncio.Semaphore | None = None

    def is_internal(self, scope: Scope) -> bool:
        """Whether the request came in on the internal listener."""
        server = scope.get("server")
        return server is not None and server[1] == self.internal_port

    def loopback_semaphore(self) -> asyncio.Semaphore:
        """The semaphore of the running event loop, made on first use in each loop."""
        loop = asyncio.get_running_loop()
        if self._loopback is None or self._loop is not loop:
            self._loop, self._loopback = loop, asyncio.Semaphore(self.loopback_limit)
        return self._loopback

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path: str = scope.get("path", "")
        if scope["type"] != "http" or path in ROOT_PATHS:
            await self.root(scope, receive, send)
            return
        internal = self.is_internal(scope)
        owner = self.table.owner(path)
        if owner is None:
            if internal and not path.startswith(API_PREFIX):
                await self.root(scope, receive, send)
            else:
                await not_found(scope, receive, send)
            return
        route = self.table.route(owner, scope["method"], path)
        exposure = None if route is None else route.exposure
        if not internal and not served_publicly(exposure, self.auth_mode):
            await not_found(scope, receive, send)
            return
        app = self.services[owner]
        with structlog.contextvars.bound_contextvars(service=owner):
            if route is not None and route.loopback:
                async with self.loopback_semaphore():
                    await app(scope, receive, send)
            else:
                await app(scope, receive, send)


async def not_found(scope: Scope, receive: Receive, send: Send) -> None:
    """The 404 ``route-not-found`` problem."""
    error = RouteNotFoundError("No route serves this method and path on this listener.")
    response = problem_response(
        Request(scope),
        status=404,
        type_uri=error.type_uri,
        title=error.title,
        detail=error.detail,
    )
    await response(scope, receive, send)
