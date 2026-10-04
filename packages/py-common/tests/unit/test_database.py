"""Pooled engines sized by the settings."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.pool import QueuePool

from py_common.database import create_pooled_engine, max_connections, pool_options
from py_common.settings import Settings


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_the_defaults_are_a_small_pool() -> None:
    defaults = settings()
    assert (defaults.db_pool_size, defaults.db_max_overflow) == (3, 2)
    assert max_connections(defaults) == 5
    assert pool_options(defaults) == {
        "poolclass": QueuePool,
        "pool_size": 3,
        "max_overflow": 2,
        "pool_pre_ping": True,
    }


def test_a_pooled_engine_follows_the_settings(tmp_path: Path) -> None:
    sized = settings(db_pool_size=4, db_max_overflow=0)
    engine = create_pooled_engine(sized, f"sqlite:///{tmp_path / 'pool.db'}")
    try:
        pool = engine.pool
        assert isinstance(pool, QueuePool)
        assert (pool.size(), pool._max_overflow) == (4, 0)
        assert pool._pre_ping is True
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar() == 1
    finally:
        engine.dispose()
    assert max_connections(sized) == 4


def test_the_engine_reads_the_database_url_by_default(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'default.db'}"
    engine = create_pooled_engine(settings(database_url=url))
    try:
        assert engine.url.render_as_string() == url
    finally:
        engine.dispose()


@pytest.mark.parametrize(("field", "value"), [("db_pool_size", 0), ("db_max_overflow", -1)])
def test_a_pool_needs_a_connection_and_no_negative_overflow(field: str, value: int) -> None:
    with pytest.raises(ValidationError, match=field):
        settings(**{field: value})
