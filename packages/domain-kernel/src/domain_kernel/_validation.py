"""Checks shared by the value objects. Every failure is an InvariantViolationError.

The helpers take ``object`` so that a runtime check on an annotated field is still a real
branch for the type checker.
"""

import math
from collections.abc import Mapping
from datetime import date, datetime
from types import MappingProxyType

from domain_kernel.errors import InvariantViolationError


def require_instance[T](value: object, kind: type[T], name: str) -> T:
    """Return ``value`` when it is an instance of ``kind``."""
    if not isinstance(value, kind):
        raise InvariantViolationError(
            f"{name} must be {kind.__name__}, got {value.__class__.__name__}"
        )
    return value


def require_bool(value: object, name: str) -> bool:
    """Return ``value`` when it is a bool."""
    return require_instance(value, bool, name)


def require_text(value: object, name: str, *, strip: bool = True) -> str:
    """Return ``value`` when it is a non-blank string.

    With ``strip`` (the default) the string must also carry no leading or trailing whitespace;
    ``strip=False`` keeps verbatim text such as a quote.
    """
    text = require_instance(value, str, name)
    if not text.strip():
        raise InvariantViolationError(f"{name} must not be blank")
    if strip and text != text.strip():
        raise InvariantViolationError(f"{name} must not have leading or trailing whitespace")
    return text


def require_int(value: object, name: str, *, minimum: int | None = None) -> int:
    """Return ``value`` when it is an int (not a bool) of at least ``minimum``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvariantViolationError(f"{name} must be an integer, got {value.__class__.__name__}")
    if minimum is not None and value < minimum:
        raise InvariantViolationError(f"{name} must be at least {minimum}, got {value}")
    return value


def require_date(value: object, name: str) -> date:
    """Return ``value`` when it is a date and not a datetime."""
    if isinstance(value, datetime) or not isinstance(value, date):
        raise InvariantViolationError(
            f"{name} must be a date without a time, got {value.__class__.__name__}"
        )
    return value


def require_aware(value: object, name: str) -> datetime:
    """Return ``value`` when it is a timezone-aware datetime."""
    if not isinstance(value, datetime):
        raise InvariantViolationError(f"{name} must be a datetime, got {value.__class__.__name__}")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise InvariantViolationError(f"{name} must be timezone-aware")
    return value


def require_finite(value: object, name: str) -> float:
    """Return ``value`` when it is a finite int or float (not a bool)."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise InvariantViolationError(f"{name} must be a finite number, got {value!r}")
    return value


def freeze_mapping(value: object, name: str) -> Mapping[str, object]:
    """Copy a mapping with string keys into a read-only proxy."""
    if not isinstance(value, Mapping):
        raise InvariantViolationError(f"{name} must be a mapping, got {value.__class__.__name__}")
    for key in value:
        if not isinstance(key, str):
            raise InvariantViolationError(f"{name} keys must be strings, got {key!r}")
    return MappingProxyType(dict(value))
