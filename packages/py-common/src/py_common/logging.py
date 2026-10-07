"""Structured JSON logging (guide section 18).

One structlog ``ProcessorFormatter`` renders both structlog events and stdlib records (uvicorn,
sqlalchemy, alembic), so every line carries ``timestamp``, ``level``, ``logger``, ``event``,
``service``, ``correlation_id``, ``tenant_id`` and ``actor``, plus ``trace_id`` and ``span_id``
inside a recording OpenTelemetry span. Request-scoped fields are bound via contextvars; ``actor``
names who acted (``user:<uuid>``, ``service:<client>`` or ``anonymous``) and is bound by
``py_common.auth.context``, and a field nothing bound is null. ``service`` is the configured
service name unless a ``service`` context variable is bound: a process that hosts several
services binds the owning service per request, so its lines stay attributable.

Every line is masked for personal identifiers (``redact_pii``, always on): GSTINs, PANs, Aadhaar
numbers, phone numbers and email addresses become ``[GSTIN]``, ``[PAN]``, ``[AADHAAR]``,
``[PHONE]`` and ``[EMAIL]`` (``domain_kernel.pii.mask_pii_in``, also in lower case, glued to an
underscore or digits, or URL-encoded) in the event text, in every other field at any depth (inside
dicts, lists and tuples) and, in JSON output, in the exception. Any other value (an exception, a
pydantic model, a dataclass, a set, bytes) is turned into its ``repr`` and masked, since the JSON
renderer would print that ``repr`` as it is; a number, a boolean and None stay as they are.
Masking runs last in the shared chain, so it covers structlog events and stdlib records alike.

It leaves alone, at the top of the line only, the fields every line carries (``timestamp``,
``level``, ``logger``, ``service``, ``correlation_id``, ``tenant_id``, ``actor``, ``trace_id``,
``span_id``); the value of any key ending in ``_id`` or ``_ids``, at any depth; and every UUID in
its canonical form and every lower-case hex id of 16 or more (a SHA-256 digest, a ``uuid4().hex``,
a span id) standing on its own, wherever it is (a request path, a workflow id, the event text).
Inside the exception nothing is left alone: a frame's local named ``tenant_id`` is masked too.
By design, any other ten-digit number from 6 to 9, and any twelve-digit one from 2 to 9, is
masked as a phone or an Aadhaar number, whatever it is: an amount or a reference. Log such an id
under a key ending in ``_id`` to keep it whole, or a number as an int.

``redact_pii`` never raises into the code that logs: a value it cannot mask (a ``repr`` that
fails, say) turns the line into ``log_redaction_failed`` with the fields above, the masked event
text and the error's type, and a value nested deeper than the kernel's ``MAX_DEPTH`` or inside
itself is cut there.

A JSON traceback carries the locals of its frames only where ``env`` is local or test
(``FRAME_LOCALS_ENVIRONMENTS``): anywhere else a local may hold a request body, a token or a
secret, which the collector must never get. Where they are carried, each is cut to 80 characters
before it is masked, so an identifier cut in two may show in part; that stays on a developer's
machine. The console renderer (``CW_LOG_JSON=false``, for a developer's terminal, and refused in
staging and production by ``cw-mvp check-config``) formats a traceback after the chain, so its
traceback is not masked.
"""

import contextlib
import logging
import sys
from typing import Final, TextIO

import structlog
from opentelemetry import trace
from opentelemetry.trace import format_span_id, format_trace_id
from structlog.processors import ExceptionRenderer
from structlog.tracebacks import ExceptionDictTransformer
from structlog.typing import EventDict, Processor, WrappedLogger

from domain_kernel.pii import ID_KEY_SUFFIXES, mask_pii_in

_CONTEXT_FIELDS = ("correlation_id", "tenant_id", "actor")
UNMASKED_FIELDS: Final = frozenset(
    {
        "timestamp",
        "level",
        "logger",
        "service",
        "correlation_id",
        "tenant_id",
        "actor",
        "trace_id",
        "span_id",
    }
)
"""The fields every line carries, which ``redact_pii`` leaves alone at the top of the line."""
_LEFT_AS_THEY_ARE: Final = UNMASKED_FIELDS | {
    # The console renderer formats the exception from it after the chain (local and test).
    "exc_info",
    # ProcessorFormatter's own keys on a stdlib record, which remove_processors_meta drops.
    "_record",
    "_from_structlog",
}
_STRUCTLOG_META: Final = frozenset({"_record", "_from_structlog"})
_EXCEPTION: Final = "exception"
"""Where the JSON traceback goes: masked whole, with no field and no id key left alone."""
FRAME_LOCALS_ENVIRONMENTS: Final = frozenset({"local", "test"})
"""Where a JSON traceback carries the locals of its frames."""
REDACTION_FAILED: Final = "log_redaction_failed"
"""The event of a line ``redact_pii`` could not mask, which stands in for it."""


def _add_service(service_name: str) -> Processor:
    def processor(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("service", service_name)
        return event_dict

    return processor


def _ensure_context_fields(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    for field in _CONTEXT_FIELDS:
        event_dict.setdefault(field, None)
    return event_dict


def add_trace_context(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """The current span's ids, when a span is recording (no-op without telemetry)."""
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict.setdefault("trace_id", format_trace_id(context.trace_id))
        event_dict.setdefault("span_id", format_span_id(context.span_id))
    return event_dict


def redact_pii(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Mask the personal identifiers in every value of the line (``domain_kernel.pii``), except
    the fields every line carries and the value of a key ending in ``_id`` or ``_ids``; inside the
    exception, everything. A value that is not text, a number, a boolean or None is masked as its
    ``repr``. Nested values are masked as copies, so a dict or list the caller logged is never
    changed. Never raises: a line it cannot mask becomes ``REDACTION_FAILED``."""
    try:
        return {key: _redacted(key, value) for key, value in event_dict.items()}
    except Exception as error:  # a log call must never fail the code that makes it
        return _redaction_failed(event_dict, error)


def _redacted(key: str, value: object) -> object:
    if key in _LEFT_AS_THEY_ARE or key.endswith(ID_KEY_SUFFIXES):
        return value
    if key == _EXCEPTION:
        return mask_pii_in(value, id_keys=False, render=repr)
    return mask_pii_in(value, render=repr)


def _redaction_failed(event_dict: EventDict, error: Exception) -> EventDict:
    """The line that stands in for one ``redact_pii`` could not mask: the fields every line
    carries when they are plain values, the logged event masked when it is text, and the type of
    the error. Nothing else of the line is kept."""
    line: EventDict = {
        key: value
        for key, value in event_dict.items()
        if key in _STRUCTLOG_META or (key in UNMASKED_FIELDS and _plain(value))
    }
    line["event"] = REDACTION_FAILED
    line["error_type"] = type(error).__name__
    logged = event_dict.get("event")
    if isinstance(logged, str):
        with contextlib.suppress(Exception):
            line["logged_event"] = mask_pii_in(logged)
    return line


def _plain(value: object) -> bool:
    return value is None or isinstance(value, str | bool | int | float)


def configure_logging(
    *,
    service_name: str,
    log_level: str = "INFO",
    json_output: bool = True,
    stream: TextIO | None = None,
    env: str | None = None,
) -> None:
    """Configure structlog and the stdlib root logger. Safe to call more than once (tests).

    ``env`` is the deployment's ``CW_ENV``: a JSON traceback carries its frames' locals only in
    ``FRAME_LOCALS_ENVIRONMENTS``, and None, a process that does not say, carries none."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        _add_service(service_name),
        _ensure_context_fields,
        add_trace_context,
        structlog.processors.StackInfoRenderer(),
    ]
    renderer: Processor
    if json_output:
        frame_locals = env in FRAME_LOCALS_ENVIRONMENTS
        shared.append(ExceptionRenderer(ExceptionDictTransformer(show_locals=frame_locals)))
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()
    # Last, after _ensure_context_fields and the traceback: every field of the line is in place.
    shared.append(redact_pii)

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    if name is None:
        return structlog.stdlib.get_logger()
    return structlog.stdlib.get_logger(name)


def bind_request_context(*, correlation_id: str, tenant_id: str | None = None) -> None:
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id, tenant_id=tenant_id)


def clear_request_context() -> None:
    structlog.contextvars.clear_contextvars()
