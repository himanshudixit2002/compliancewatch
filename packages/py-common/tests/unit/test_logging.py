import io
import json
import logging

import structlog

from py_common.logging import configure_logging, get_logger


def _last_record(buffer: io.StringIO) -> dict[str, object]:
    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    assert lines, "nothing was logged"
    record: dict[str, object] = json.loads(lines[-1])
    return record


def test_json_line_carries_service_and_context_fields() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    get_logger("py_common.tests").info("hello", foo=1)
    record = _last_record(buffer)
    assert record["event"] == "hello"
    assert record["service"] == "test-svc"
    assert record["level"] == "info"
    assert record["foo"] == 1
    assert record["logger"] == "py_common.tests"
    assert "timestamp" in record
    assert record["correlation_id"] is None
    assert record["tenant_id"] is None


def test_bound_contextvars_appear_on_every_line() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    with structlog.contextvars.bound_contextvars(correlation_id="abc", tenant_id="t1"):
        get_logger("py_common.tests").warning("inside")
    record = _last_record(buffer)
    assert record["correlation_id"] == "abc"
    assert record["tenant_id"] == "t1"


def test_stdlib_records_are_rendered_through_the_same_formatter() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    logging.getLogger("uvicorn.access").info("foreign record")
    record = _last_record(buffer)
    assert record["event"] == "foreign record"
    assert record["service"] == "test-svc"
    assert record["logger"] == "uvicorn.access"
    assert record["level"] == "info"
