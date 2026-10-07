import hashlib
import io
import json
import logging
import timeit
from dataclasses import dataclass
from typing import Any

import structlog
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from domain_kernel.pii import CYCLE, MAX_DEPTH, TOO_DEEP
from py_common.logging import (
    REDACTION_FAILED,
    configure_logging,
    get_logger,
    redact_pii,
)


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
    tenant_id = "9876543210"
    raise ValueError(f"refused {contact} ({len(email)}, {len(tenant_id)})")


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
        _lines(buffer)[-2:],
        ["refused PAN [PAN] (17, 10)", "refused phone [PHONE] (17, 10)"],
        strict=True,
    ):
        [exception] = line["exception"]
        assert exception["exc_value"] == message
        frame = exception["frames"][-1]
        assert frame["name"] == "_refuse"
        assert frame["locals"]["email"] == "'[EMAIL]'"
        assert frame["locals"]["tenant_id"] == "'[PHONE]'", "nothing in the exception is exempt"
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


def test_the_fields_every_line_carries_are_left_alone_at_the_top_of_the_line_only() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    get_logger("py_common.tests").info(
        "stored",
        payload={"service": "9876543210", "actor": "owner@example.com", "level": "234567890123"},
    )
    record = _last_record(buffer)
    assert record["payload"] == {"service": "[PHONE]", "actor": "[EMAIL]", "level": "[AADHAAR]"}


@dataclass
class _Contact:
    email: str


class _Profile(BaseModel):
    pan: str


def test_a_value_that_is_not_text_is_masked_as_its_repr() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    get_logger("py_common.tests").info(
        "values",
        error=ValueError("no account for owner@example.com"),
        model=_Profile(pan="ABCDE1234F"),
        contact=_Contact(email="owner@example.com"),
        phones={"9876543210"},
        frozen=frozenset({"234567890123"}),
        raw=b"PAN ABCDE1234F",
        nested={"items": [_Contact(email="a@b.co")]},
        count=7,
        ratio=0.5,
        flag=True,
        nothing=None,
    )
    record = _last_record(buffer)
    assert record["error"] == "ValueError('no account for [EMAIL]')"
    assert record["model"] == "_Profile(pan='[PAN]')"
    assert record["contact"] == "_Contact(email='[EMAIL]')"
    assert record["phones"] == "{'[PHONE]'}"
    assert record["frozen"] == "frozenset({'[AADHAAR]'})"
    assert record["raw"] == "b'PAN [PAN]'"
    assert record["nested"] == {"items": ["_Contact(email='[EMAIL]')"]}
    assert [record[key] for key in ("count", "ratio", "flag", "nothing")] == [7, 0.5, True, None]
    for raw in ("owner@example.com", "ABCDE1234F", "9876543210", "234567890123", "a@b.co"):
        assert raw not in buffer.getvalue()


def test_a_value_inside_itself_or_nested_too_deep_is_cut_and_the_line_still_written() -> None:
    """Before, these raised RecursionError out of the log call."""
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    looped: list[object] = ["9876543210"]
    looped.append(looped)
    deep: object = "owner@example.com"
    for _ in range(2_000):
        deep = {"inner": deep}
    tuples: object = "ABCDE1234F"
    for _ in range(1_000):
        tuples = (tuples,)
    get_logger("py_common.tests").info("values", looped=looped, deep=deep, tuples=tuples)
    record = _last_record(buffer)
    assert record["looped"] == ["[PHONE]", CYCLE]
    for key in ("deep", "tuples"):
        value, depth = record[key], 0
        while isinstance(value, dict | list):
            value = value["inner"] if isinstance(value, dict) else value[0]
            depth += 1
        assert (value, depth) == (TOO_DEEP, MAX_DEPTH)


class _Unprintable:
    def __repr__(self) -> str:
        raise RuntimeError("no repr of 9876543210")


def test_a_line_it_cannot_mask_is_replaced_and_the_log_call_never_raises() -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    with structlog.contextvars.bound_contextvars(correlation_id="c-1", actor="anonymous"):
        get_logger("py_common.tests").warning(
            "profile of owner@example.com", value=_Unprintable(), phone="9876543210"
        )
    record = _last_record(buffer)
    assert record["event"] == REDACTION_FAILED
    assert record["error_type"] == "RuntimeError"
    assert record["logged_event"] == "profile of [EMAIL]"
    assert (record["correlation_id"], record["actor"]) == ("c-1", "anonymous")
    assert (record["level"], record["service"]) == ("warning", "test-svc")
    assert "value" not in record
    assert "phone" not in record
    assert "9876543210" not in buffer.getvalue()


def test_a_stdlib_records_own_keys_survive_a_line_it_cannot_mask() -> None:
    """ProcessorFormatter adds _record and _from_structlog to a stdlib record's line and removes
    them after the chain, so the line that stands in keeps them."""
    record = logging.LogRecord("httpx", logging.INFO, __file__, 1, "msg", (), None)
    line = redact_pii(
        None,
        "info",
        {"event": "msg", "_record": record, "_from_structlog": False, "value": _Unprintable()},
    )
    assert line["_record"] is record
    assert line["_from_structlog"] is False
    assert line["event"] == REDACTION_FAILED


def test_a_64_kb_request_path_is_logged_in_well_under_50_ms() -> None:
    """The email pattern before the fix took 2.2 s on this line, blocking the event loop."""
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    access = logging.getLogger("uvicorn.access")
    path = "/v1/" + "a." * 32_768 + "@"
    best = min(
        timeit.repeat(lambda: access.info('"GET %s HTTP/1.1" 404', path), number=1, repeat=3)
    )
    assert best < 0.05, f"{best * 1000:.1f} ms"
    assert _last_record(buffer)["event"] == f'"GET {path} HTTP/1.1" 404'


_HEX = "0123456789abcdef"
_IDS = st.one_of(
    st.binary(max_size=64).map(lambda data: hashlib.sha256(data).hexdigest()),
    st.uuids().map(lambda value: value.hex),
    st.integers(min_value=1, max_value=2**64 - 1).map(lambda span: f"{span:016x}"),
    st.builds(
        lambda head, letter, tail: head + letter + tail,
        st.text(alphabet=_HEX, min_size=15, max_size=40),
        st.sampled_from("abcdef"),
        st.text(alphabet=_HEX, max_size=40),
    ),
    st.uuids().map(str),
)
"""SHA-256 digests, ``.hex`` ids, 16-hex span ids, other lower-case hex ids and UUIDs."""


@given(_IDS)
def test_hex_ids_and_uuids_are_never_altered_on_a_line(value: str) -> None:
    buffer = io.StringIO()
    configure_logging(service_name="test-svc", stream=buffer)
    get_logger("py_common.tests").info(
        f"workflow pipeline-triage-{value} ended",
        key=f"ab/{value}",
        workflows=[f"extract-knowledge-{value}", f"{value}-v2", f"tenant-{value}"],
    )
    logging.getLogger("uvicorn.access").info('"GET /v1/documents/%s HTTP/1.1" 200', value)
    first, second = _lines(buffer)[-2:]
    assert first["event"] == f"workflow pipeline-triage-{value} ended"
    assert first["key"] == f"ab/{value}"
    assert first["workflows"] == [f"extract-knowledge-{value}", f"{value}-v2", f"tenant-{value}"]
    assert second["event"] == f'"GET /v1/documents/{value} HTTP/1.1" 200'
