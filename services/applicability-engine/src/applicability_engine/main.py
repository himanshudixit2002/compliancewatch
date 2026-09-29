"""Composition root for the applicability-engine service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
"""

from fastapi import FastAPI

from applicability_engine import __version__
from applicability_engine.api.router import router
from py_common.app import create_app, module_app
from py_common.auth.fastapi import Authenticator
from py_common.settings import Settings

SERVICE_NAME = "applicability-engine"


def build_app(
    settings: Settings | None = None, *, authenticator: Authenticator | None = None
) -> FastAPI:
    """``authenticator`` replaces the one ``CW_AUTH_MODE`` describes; a process that hosts
    identity passes identity's own."""
    return create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router],
        settings=settings,
        authenticator=authenticator,
    )


def __getattr__(name: str) -> FastAPI:
    """``app`` is built on first access, so importing this module builds nothing."""
    return module_app(name, build_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("applicability_engine.main:app", host="127.0.0.1", port=8004, reload=True)
