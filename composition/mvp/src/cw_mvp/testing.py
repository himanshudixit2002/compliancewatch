"""Builders for tests and demos that run the whole app in one process without Postgres.

``mvp_settings(**overrides)`` ignores the repo ``.env``; ``MEMORY_SERVICES`` are the
``service_overrides`` that put every service with a store on its memory store, identity on its
memory billing and the gateway on its fake provider, so ``build_app(mvp_settings(),
service_overrides=MEMORY_SERVICES)`` needs nothing running.
"""

from collections.abc import Mapping
from typing import Any, Final

from cw_mvp.settings import APP_SERVICE_NAME, MvpSettings

MEMORY_SERVICES: Final[Mapping[str, Mapping[str, Any]]] = {
    "identity": {"identity_store": "memory", "billing_provider": "memory"},
    "profile": {"profile_store": "memory"},
    "rulebook": {"rulebook_store": "memory"},
    "obligation": {"obligation_store": "memory"},
    "notification": {"notification_store": "memory"},
    "llm-gateway": {"llm_ledger": "memory", "llm_provider": "fake"},
}


def mvp_settings(**overrides: Any) -> MvpSettings:
    """Settings that ignore the repo ``.env``; explicit values win over the environment."""
    values: dict[str, Any] = {"_env_file": None, "service_name": APP_SERVICE_NAME}
    values.update(overrides)
    return MvpSettings(**values)
