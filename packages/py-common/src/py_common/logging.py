"""Structured JSON logging (guide section 18).

One structlog ``ProcessorFormatter`` renders both structlog events and stdlib records (uvicorn,
sqlalchemy, alembic), so every line carries ``timestamp``, ``level``, ``logger``, ``event``,
``service``, ``correlation_id`` and ``tenant_id``. Request-scoped fields are bound via contextvars.
"""

import logging
import sys
from typing import TextIO

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

_CONTEXT_FIELDS = ("correlation_id", "tenant_id")


def _add_service(service_name: str) -> Processor:
    def processor(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
        event_dict["service"] = service_name
        return event_dict

    return processor


def _ensure_context_fields(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    for field in _CONTEXT_FIELDS:
        event_dict.setdefault(field, None)
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
        structlog.processors.StackInfoRenderer(),
    ]
    renderer: Processor
    if json_output:
        shared.append(structlog.processors.dict_tracebacks)
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

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
