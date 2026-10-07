import io
import json
import logging
from typing import Any

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
    assert record["actor"] is None


def test_bound_contextvars_appear_on_every_line() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    with structlog.contextvars.bound_contextvars(
        correlation_id="abc", tenant_id="t1", actor="service:pipeline"
    ):
        get_logger("py_common.tests").warning("inside")
    record = _last_record(buffer)
    assert record["correlation_id"] == "abc"
    assert record["tenant_id"] == "t1"
    assert record["actor"] == "service:pipeline"


def test_every_line_carries_the_actor_null_when_unbound() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    log = get_logger("py_common.tests")
    log.info("before")
    with structlog.contextvars.bound_contextvars(actor="anonymous"):
        log.info("during")
        logging.getLogger("uvicorn.access").info("foreign during")
    log.info("after")
    lines = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
    assert [(line["event"], line["actor"]) for line in lines] == [
        ("before", None),
        ("during", "anonymous"),
        ("foreign during", "anonymous"),
        ("after", None),
    ]


def test_stdlib_records_are_rendered_through_the_same_formatter() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    logging.getLogger("uvicorn.access").info("foreign record")
    record = _last_record(buffer)
    assert record["event"] == "foreign record"
    assert record["service"] == "test-svc"
    assert record["logger"] == "uvicorn.access"
    assert record["level"] == "info"


def test_a_bound_service_wins_over_the_configured_one() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="compliancewatch-api", stream=buffer)
    log = get_logger("py_common.tests")
    with structlog.contextvars.bound_contextvars(service="rulebook"):
        log.info("inside")
        logging.getLogger("uvicorn.error").info("foreign inside")
    log.info("outside")
    lines = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
    assert [(line["event"], line["service"]) for line in lines] == [
        ("inside", "rulebook"),
        ("foreign inside", "rulebook"),
        ("outside", "compliancewatch-api"),
    ]


# ---- personal identifiers (every value below is made up) --------------------------------------

UUID_WITH_TWELVE_DIGITS = "5a3c6a0e-0d7b-4f43-9a4e-234567890123"
"""A made-up UUID whose last group, on its own, would read as an Aadhaar number."""


def _lines(buffer: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]


def test_identifiers_in_the_event_text_are_masked() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    get_logger("py_common.tests").info(
        "Example Owner: PAN ABCDE1234F, mail owner@example.com, phone 9876543210"
    )
    record = _last_record(buffer)
    assert record["event"] == "Example Owner: PAN [PAN], mail [EMAIL], phone [PHONE]"


def test_nested_values_are_masked_and_what_the_caller_logged_is_not_changed() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    payload = {
        "owner": {"email": "owner@example.com", "phones": ["+91 98765 43210"]},
        "registrations": ["29ABCDE1234F1Z5"],
        "count": 2,
    }
    get_logger("py_common.tests").info(
        "profile", payload=payload, note=("Aadhaar 2345 6789 0123", 7), size=9876543210
    )
    record = _last_record(buffer)
    assert record["payload"] == {
        "owner": {"email": "[EMAIL]", "phones": ["[PHONE]"]},
        "registrations": ["[GSTIN]"],
        "count": 2,
    }
    assert record["note"] == ["Aadhaar [AADHAAR]", 7]
    assert record["size"] == 9876543210, "a number logged as an int is not text"
    assert payload == {
        "owner": {"email": "owner@example.com", "phones": ["+91 98765 43210"]},
        "registrations": ["29ABCDE1234F1Z5"],
        "count": 2,
    }


def test_stdlib_records_are_masked() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    logging.getLogger("httpx").info("POST /v1/example?email=%s", "owner@example.com")
    logging.getLogger("uvicorn.access").info('"GET /v1/example/ABCDE1234F HTTP/1.1" 200')
    first, second = _lines(buffer)[-2:]
    assert first["event"] == "POST /v1/example?email=[EMAIL]"
    assert first["logger"] == "httpx"
    assert second["event"] == '"GET /v1/example/[PAN] HTTP/1.1" 200'


def test_the_fields_every_line_carries_and_id_keys_are_left_alone() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    with structlog.contextvars.bound_contextvars(
        correlation_id="234567890123",
        tenant_id="9876543210",
        actor="service:client-9876543210",
        trace_id="9876543210",
        span_id="234567890123",
    ):
        get_logger("py_common.tests").info(
            "stored",
            node_id="234567890123",
            obligation_ids=["234567890123", "9876543210"],
            nested={"business_id": "9876543210", "reference": "9876543210"},
            reference="234567890123",
        )
    record = _last_record(buffer)
    assert record["correlation_id"] == "234567890123"
    assert record["tenant_id"] == "9876543210"
    assert record["actor"] == "service:client-9876543210"
    assert (record["trace_id"], record["span_id"]) == ("9876543210", "234567890123")
    assert record["node_id"] == "234567890123"
    assert record["obligation_ids"] == ["234567890123", "9876543210"]
    assert record["nested"] == {"business_id": "9876543210", "reference": "[PHONE]"}
    assert record["reference"] == "[AADHAAR]"


def test_a_uuid_is_kept_whole_wherever_it_stands() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    get_logger("py_common.tests").info(
        f"resolved {UUID_WITH_TWELVE_DIGITS} for owner@example.com",
        resolved_by=UUID_WITH_TWELVE_DIGITS,
    )
    logging.getLogger("uvicorn.access").info(
        '"GET /v1/nodes/%s HTTP/1.1" 200', UUID_WITH_TWELVE_DIGITS
    )
    first, second = _lines(buffer)[-2:]
    assert first["event"] == f"resolved {UUID_WITH_TWELVE_DIGITS} for [EMAIL]"
    assert first["resolved_by"] == UUID_WITH_TWELVE_DIGITS
    assert second["event"] == f'"GET /v1/nodes/{UUID_WITH_TWELVE_DIGITS} HTTP/1.1" 200'


def test_ten_and_twelve_digit_numbers_outside_id_keys_are_masked_by_design() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    get_logger("py_common.tests").info(
        "batch 9876543210 of 234567890123",
        amount="6000000000",
        reference_id="6000000000",
        total=6000000000,
    )
    record = _last_record(buffer)
    assert record["event"] == "batch [PHONE] of [AADHAAR]"
    assert record["amount"] == "[PHONE]"
    assert record["reference_id"] == "6000000000"
    assert record["total"] == 6000000000


def _refuse(contact: str) -> None:
    email = "owner@example.com"
    raise ValueError(f"refused {contact} ({len(email)})")


def test_an_exceptions_message_and_its_frames_locals_are_masked() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    try:
        _refuse("PAN ABCDE1234F")
    except ValueError:
        get_logger("py_common.tests").exception("refused")
    try:
        _refuse("phone 9876543210")
    except ValueError:
        logging.getLogger("httpx").error("foreign refused", exc_info=True)
    for line, message in zip(
        _lines(buffer)[-2:], ["refused PAN [PAN] (17)", "refused phone [PHONE] (17)"], strict=True
    ):
        [exception] = line["exception"]
        assert exception["exc_value"] == message
        frame = exception["frames"][-1]
        assert frame["name"] == "_refuse"
        assert frame["locals"]["email"] == "'[EMAIL]'"
        assert "[" in frame["locals"]["contact"]
    assert "ABCDE1234F" not in buffer.getvalue()
    assert "owner@example.com" not in buffer.getvalue()


def test_console_output_is_masked_too() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer, json_output=False)
    get_logger("py_common.tests").info("mail owner@example.com", phone="9876543210")
    logging.getLogger("uvicorn.error").info("from ABCDE1234F")
    output = buffer.getvalue()
    assert "[EMAIL]" in output
    assert "[PHONE]" in output
    assert "from [PAN]" in output
    assert "owner@example.com" not in output
    assert "9876543210" not in output
