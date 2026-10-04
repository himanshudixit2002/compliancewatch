"""Pooled SQLAlchemy engines sized by the settings.

``create_pooled_engine(settings)`` is a sync engine on ``CW_DATABASE_URL`` (or the URL given)
with a ``QueuePool`` of ``CW_DB_POOL_SIZE`` connections that grows by up to
``CW_DB_MAX_OVERFLOW`` under load. Each connection is pinged before use, since a managed Postgres
closes idle ones. Pooling is safe with row-level security: the tenant is set with
``set_config(..., true)``, which ends with the transaction, so a connection returns to the pool
without it.

``max_connections(settings)`` is the most one such engine holds at once; a process that hosts
several services adds up one per engine of each to compare with what the database allows.
"""

from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import QueuePool

from py_common.settings import Settings


def pool_options(settings: Settings) -> dict[str, Any]:
    """The ``create_engine`` arguments of a pooled engine."""
    return {
        "poolclass": QueuePool,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_pre_ping": True,
    }


def create_pooled_engine(settings: Settings, url: str | None = None) -> Engine:
    """A sync engine on ``url``, or ``CW_DATABASE_URL`` when it is None, pooled as the settings
    say."""
    return create_engine(url or settings.database_url, **pool_options(settings))


def max_connections(settings: Settings) -> int:
    """The most connections one pooled engine holds at once."""
    return settings.db_pool_size + settings.db_max_overflow


__all__ = ["create_pooled_engine", "max_connections", "pool_options"]
