"""Builders for tests and demos that run the whole app in one process without Postgres.

``mvp_settings(**overrides)`` ignores the repo ``.env``; ``MEMORY_SERVICES`` are the
``service_overrides`` that put every service with a store on its memory store (the pipeline's
fetched files too), identity on its memory billing and the gateway on its fake provider, so
``build_app(mvp_settings(), service_overrides=MEMORY_SERVICES)`` needs nothing running.

``running_app(**overrides)`` serves that app with uvicorn on a thread, both listeners on free
ports of ``127.0.0.1`` and ``CW_MVP_INTERNAL_URL`` at the internal one, so the calls the services
make to each other go over TCP as they do in a deployment.
"""

import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Final

from cw_mvp.app import CombinedApp, build_app
from cw_mvp.serve import listener, server
from cw_mvp.settings import APP_SERVICE_NAME, MvpSettings

MEMORY_SERVICES: Final[Mapping[str, Mapping[str, Any]]] = {
    "identity": {"identity_store": "memory", "billing_provider": "memory"},
    "profile": {"profile_store": "memory"},
    "rulebook": {"rulebook_store": "memory"},
    "applicability-engine": {"applicability_engine_store": "memory"},
    "obligation": {"obligation_store": "memory"},
    "notification": {"notification_store": "memory"},
    "llm-gateway": {"llm_ledger": "memory", "llm_provider": "fake"},
    "eval": {"eval_store": "memory"},
    "pipeline": {"pipeline_store": "memory", "pipeline_raw_store": "memory"},
}
LOCALHOST: Final = "127.0.0.1"
STARTUP_SECONDS: Final = 20.0


def mvp_settings(**overrides: Any) -> MvpSettings:
    """Settings that ignore the repo ``.env``; explicit values win over the environment."""
    values: dict[str, Any] = {"_env_file": None, "service_name": APP_SERVICE_NAME}
    values.update(overrides)
    return MvpSettings(**values)


@contextmanager
def running_app(
    *,
    service_overrides: Mapping[str, Mapping[str, Any]] = MEMORY_SERVICES,
    build_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    **overrides: Any,
) -> Iterator[CombinedApp]:
    """The app on ``service_overrides`` (the memory stores), served until the block ends.
    ``overrides`` are ``MvpSettings`` values; the log level is WARNING unless they say."""
    public, internal = listener(LOCALHOST, 0), listener(LOCALHOST, 0)
    try:
        internal_port = internal.getsockname()[1]
        settings = mvp_settings(
            **{
                "log_level": "WARNING",
                **overrides,
                "mvp_public_port": public.getsockname()[1],
                "mvp_internal_port": internal_port,
                "mvp_internal_url": f"http://{LOCALHOST}:{internal_port}",
            }
        )
        app = build_app(
            settings, service_overrides=service_overrides, build_overrides=build_overrides
        )
        running = server(app, settings)
        thread = threading.Thread(
            target=running.run, kwargs={"sockets": [public, internal]}, daemon=True
        )
        thread.start()
        try:
            deadline = time.monotonic() + STARTUP_SECONDS
            while not running.started:
                if not thread.is_alive():
                    raise RuntimeError("the app stopped while starting")
                if time.monotonic() > deadline:
                    raise RuntimeError("the app did not start")
                time.sleep(0.05)
            yield app
        finally:
            running.should_exit = True
            thread.join(STARTUP_SECONDS)
    finally:
        public.close()
        internal.close()
