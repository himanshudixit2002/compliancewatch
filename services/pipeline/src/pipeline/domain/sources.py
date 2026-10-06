"""The sources the pipeline reads, as it records them (the ``source`` table).

A ``SourceDefinition`` says what a source is: its key, the adapter type that reads it with that
type's parameters, how often it is read, and the regulator and document type of what it lists.
The built-in definitions live in the adapter registry (``infrastructure.adapters``). A ``Source``
is the stored row: the definition's key, adapter type, parameters and cadence, whether it is
enabled or paused, and how far the last crawl got. The pipeline adds the row the first time it
stores a document of the source and never overwrites one that exists.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Self

from domain_kernel._validation import (
    freeze_mapping,
    require_aware,
    require_bool,
    require_instance,
    require_text,
)
from domain_kernel.documents import DocumentType
from domain_kernel.errors import InvariantViolationError

SOURCE_KEY_PATTERN: Final = r"^[a-z][a-z0-9_]{0,62}$"
"""``cbic_notifications``: lower case, digits and underscores, at most 63 characters."""
ADAPTER_TYPE_PATTERN: Final = r"^[a-z][a-z0-9_]{0,39}$"
"""``cbic``: the name of an adapter type in the registry."""
MIN_CADENCE: Final = timedelta(minutes=1)
MAX_ERROR_CHARS: Final = 2_000

_SOURCE_KEY = re.compile(SOURCE_KEY_PATTERN)
_ADAPTER_TYPE = re.compile(ADAPTER_TYPE_PATTERN)


def require_source_key(value: object, name: str = "source_key") -> str:
    key = require_instance(value, str, name)
    if not _SOURCE_KEY.fullmatch(key):
        raise InvariantViolationError(f"{name} must match {SOURCE_KEY_PATTERN}, got {key!r}")
    return key


def _require_adapter_type(value: object) -> str:
    kind = require_instance(value, str, "adapter_type")
    if not _ADAPTER_TYPE.fullmatch(kind):
        raise InvariantViolationError(
            f"adapter_type must match {ADAPTER_TYPE_PATTERN}, got {kind!r}"
        )
    return kind


def _require_cadence(value: object) -> timedelta:
    cadence = require_instance(value, timedelta, "cadence")
    if cadence < MIN_CADENCE:
        raise InvariantViolationError(f"cadence must be at least {MIN_CADENCE}, got {cadence}")
    return cadence


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    """What a source is. ``parameters`` are the adapter type's, as JSON values."""

    key: str
    adapter_type: str
    parameters: Mapping[str, object]
    cadence: timedelta
    regulator: str
    doc_type: DocumentType

    def __post_init__(self) -> None:
        require_source_key(self.key, "key")
        _require_adapter_type(self.adapter_type)
        object.__setattr__(self, "parameters", freeze_mapping(self.parameters, "parameters"))
        _require_cadence(self.cadence)
        require_text(self.regulator, "regulator")
        require_instance(self.doc_type, DocumentType, "doc_type")


@dataclass(frozen=True, slots=True)
class Source:
    """A source as stored. ``watermark`` is how far the last crawl got, in the adapter type's
    terms (None before the first); ``last_error`` is empty after a crawl that went well."""

    key: str
    adapter_type: str
    parameters: Mapping[str, object]
    cadence: timedelta
    created_at: datetime
    updated_at: datetime
    enabled: bool = True
    paused: bool = False
    last_fetch_at: datetime | None = None
    watermark: Mapping[str, object] | None = None
    last_error: str = ""

    def __post_init__(self) -> None:
        require_source_key(self.key, "key")
        _require_adapter_type(self.adapter_type)
        object.__setattr__(self, "parameters", freeze_mapping(self.parameters, "parameters"))
        _require_cadence(self.cadence)
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise InvariantViolationError("updated_at must not be before created_at")
        require_bool(self.enabled, "enabled")
        require_bool(self.paused, "paused")
        if self.last_fetch_at is not None:
            require_aware(self.last_fetch_at, "last_fetch_at")
        if self.watermark is not None:
            object.__setattr__(self, "watermark", freeze_mapping(self.watermark, "watermark"))
        error = require_instance(self.last_error, str, "last_error")
        if len(error) > MAX_ERROR_CHARS:
            raise InvariantViolationError(f"last_error must be at most {MAX_ERROR_CHARS} chars")

    @classmethod
    def of(cls, definition: SourceDefinition, now: datetime) -> Self:
        """The row of a source seen for the first time: enabled, never fetched."""
        require_instance(definition, SourceDefinition, "definition")
        return cls(
            key=definition.key,
            adapter_type=definition.adapter_type,
            parameters=definition.parameters,
            cadence=definition.cadence,
            created_at=now,
            updated_at=now,
        )
