"""The alembic helpers create and drop both tables; checked on sqlite here, on Postgres in
tests/integration."""

from collections.abc import Iterator

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, create_engine, inspect

from py_common.outbox.schema import (
    OUTBOX_TABLE,
    PENDING_INDEX,
    PROCESSED_TABLE,
    PUBLISHED_INDEX,
    create_outbox_table,
    create_processed_event_table,
    drop_outbox_table,
    drop_processed_event_table,
    metadata,
    outbox_event,
    processed_event,
    table_names,
)


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    yield engine
    engine.dispose()


def test_helpers_create_the_same_tables_as_the_metadata(engine: Engine) -> None:
    with engine.begin() as connection:
        op = Operations(MigrationContext.configure(connection))
        create_outbox_table(op)
        create_processed_event_table(op)
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {OUTBOX_TABLE, PROCESSED_TABLE} == set(table_names())
    outbox_columns = {column["name"] for column in inspector.get_columns(OUTBOX_TABLE)}
    assert outbox_columns == {column.name for column in outbox_event.columns}
    processed_columns = {column["name"] for column in inspector.get_columns(PROCESSED_TABLE)}
    assert processed_columns == {column.name for column in processed_event.columns}
    assert {index["name"] for index in inspector.get_indexes(OUTBOX_TABLE)} == {
        PENDING_INDEX,
        PUBLISHED_INDEX,
    }
    assert inspector.get_pk_constraint(PROCESSED_TABLE)["constrained_columns"] == [
        "consumer_group",
        "event_id",
    ]


def test_helpers_drop_what_they_created(engine: Engine) -> None:
    with engine.begin() as connection:
        op = Operations(MigrationContext.configure(connection))
        create_outbox_table(op)
        create_processed_event_table(op)
    with engine.begin() as connection:
        op = Operations(MigrationContext.configure(connection))
        drop_processed_event_table(op)
        drop_outbox_table(op)
    assert inspect(engine).get_table_names() == []


def test_metadata_creates_the_tables_too(engine: Engine) -> None:
    metadata.create_all(engine)
    assert set(inspect(engine).get_table_names()) == {OUTBOX_TABLE, PROCESSED_TABLE}
