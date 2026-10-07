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
``[PHONE]`` and ``[EMAIL]`` (``domain_kernel.pii``) in the event text, in every other text field
at any depth (inside dicts, lists and tuples) and, in JSON output, in the exception: its message
and the locals of its frames. Masking runs last in the shared chain, so it covers structlog events
and stdlib records alike. It leaves alone the fields every line carries (``timestamp``,
``level``, ``logger``, ``service``, ``correlation_id``, ``tenant_id``, ``actor``, ``trace_id``,
``span_id``) and the value of any key ending in ``_id`` or ``_ids``, at any depth. By design,
any other ten-digit number from 6 to 9, and any twelve-digit one from 2 to 9, is masked as a
phone or an Aadhaar number, whatever it is: an amount, a reference, or a piece of a UUID in a URL
or in the event text. Log an id under a key ending in ``_id`` to keep it whole. Only text is
masked: a number logged as an int stays as it is. The console renderer (``CW_LOG_JSON=false``,
for a developer's terminal) formats a traceback after the chain, so its traceback is not masked.
"""

import logging
import sys
from typing import Final, TextIO

import structlog
from opentelemetry import trace
from opentelemetry.trace import format_span_id, format_trace_id
from structlog.typing import EventDict, Processor, WrappedLogger

from domain_kernel.pii import mask_pii_in

_CONTEXT_FIELDS = ("correlation_id", "tenant_id", "actor")
_UNMASKED_FIELDS: Final = frozenset(
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
        # The console renderer formats the exception from it after the chain.
        "exc_info",
    }
)
"""The fields ``redact_pii`` leaves alone, besides any key ending in ``_id`` or ``_ids``."""


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
    """Mask the personal identifiers in every text of the line (``domain_kernel.pii``), except
    in the fields every line carries and under a key ending in ``_id`` or ``_ids``. Nested values
    are masked as copies, so a dict or list the caller logged is never changed."""
    masked = mask_pii_in(event_dict, keep=_UNMASKED_FIELDS)
    if isinstance(masked, dict):  # a mapping always comes back as a dict
        event_dict.update(masked)
    return event_dict


def configure_logging(
    *,
    service_name: str,
    log_level: str = "INFO",
    json_output: bool = True,
    stream: TextIO | None = None,
) -> None:
    """Configure structlog and the stdlib root logger. Safe to call more than once (tests)."""
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
        shared.append(structlog.processors.dict_tracebacks)
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
