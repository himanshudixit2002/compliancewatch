"""The sources the pipeline reads, as it records them (the ``source`` table).

A ``SourceDefinition`` says what a source is: its key, the adapter type that reads it with that
type's parameters, how often it is read, the regulator and document type of what it lists, and
the name people know it by. The built-in definitions live in the adapter registry
(``infrastructure.adapters``). A ``Source`` is the stored row: the definition's key, name,
adapter type, parameters and cadence, whether it is enabled or paused, and how far the last crawl
got. The worker inserts the built-in sources the table lacks when it starts; an admin adds
others and edits any (``application.sources``); the crawl records how each crawl went
(``Source.crawled``).

A source's id is UUID v5 of its key (``source_id_of``), so the same source has the same id in
every environment.

The watermark is the newest publication date up to which every document the source listed is
stored, as ``{"published_on": "2026-10-01"}``; the crawl lists again from a week before it
(``domain.crawl``).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Final, Self
from uuid import NAMESPACE_URL, uuid5

from domain_kernel._validation import (
    freeze_mapping,
    require_aware,
    require_bool,
    require_instance,
    require_text,
)
from domain_kernel.documents import DocumentType
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import SourceId

SOURCE_KEY_PATTERN: Final = r"^[a-z][a-z0-9_]{0,62}$"
"""``cbic_notifications``: lower case, digits and underscores, at most 63 characters."""
ADAPTER_TYPE_PATTERN: Final = r"^[a-z][a-z0-9_]{0,39}$"
"""``cbic``: the name of an adapter type in the registry."""
MIN_CADENCE: Final = timedelta(minutes=1)
MAX_CADENCE: Final = timedelta(days=31)
MAX_ERROR_CHARS: Final = 2_000
MAX_NAME_CHARS: Final = 200
SOURCE_NAMESPACE: Final = "https://compliancewatch.invalid/sources/"
WATERMARK_FIELD: Final = "published_on"

_SOURCE_KEY = re.compile(SOURCE_KEY_PATTERN)
_ADAPTER_TYPE = re.compile(ADAPTER_TYPE_PATTERN)


def source_id_of(key: str) -> SourceId:
    """The source's id: UUID v5 of its key, the same in every environment."""
    return SourceId(uuid5(NAMESPACE_URL, SOURCE_NAMESPACE + require_source_key(key, "key")))


def watermark_of(published_on: date | None) -> Mapping[str, object] | None:
    """The stored form of a watermark date."""
    return None if published_on is None else {WATERMARK_FIELD: published_on.isoformat()}


def watermark_date(watermark: Mapping[str, object] | None) -> date | None:
    """The date a stored watermark holds; None for none, or for a shape this code did not
    write (the crawl then lists as for a new source)."""
    if watermark is None:
        return None
    value = watermark.get(WATERMARK_FIELD)
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


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


def _require_name(value: object) -> str:
    name = require_instance(value, str, "name")
    if len(name) > MAX_NAME_CHARS or name != name.strip():
        raise InvariantViolationError(
            f"name must be at most {MAX_NAME_CHARS} characters with no surrounding spaces"
        )
    return name


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    """What a source is. ``parameters`` are the adapter type's, as JSON values."""

    key: str
    adapter_type: str
    parameters: Mapping[str, object]
    cadence: timedelta
    regulator: str
    doc_type: DocumentType
    name: str = ""

    def __post_init__(self) -> None:
        require_source_key(self.key, "key")
        _require_adapter_type(self.adapter_type)
        object.__setattr__(self, "parameters", freeze_mapping(self.parameters, "parameters"))
        _require_cadence(self.cadence)
        require_text(self.regulator, "regulator")
        require_instance(self.doc_type, DocumentType, "doc_type")
        _require_name(self.name)


@dataclass(frozen=True, slots=True)
class Source:
    """A source as stored. ``watermark`` is how far the crawls got (None before the first that
    listed something); ``last_fetch_at`` is when a crawl last listed the source; ``last_error`` is
    empty after a crawl that went well. ``name`` is empty for a row stored before sources had
    names; ``label`` then falls back to the key."""

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
    name: str = ""

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
        _require_name(self.name)

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
            name=definition.name,
        )

    @property
    def label(self) -> str:
        """What to call the source: its name, or its key when it has none."""
        return self.name or self.key

    @property
    def crawlable(self) -> bool:
        """Whether the schedule crawls it: enabled and not paused."""
        return self.enabled and not self.paused

    @property
    def watermark_date(self) -> date | None:
        return watermark_date(self.watermark)

    def edited(
        self,
        now: datetime,
        *,
        name: str | None = None,
        cadence: timedelta | None = None,
        enabled: bool | None = None,
        paused: bool | None = None,
        parameters: Mapping[str, object] | None = None,
    ) -> Self:
        """The source with what a person changed; anything not given stays. ``parameters`` must
        be the adapter type's already (``AdapterTypes.describe``)."""
        if cadence is not None and cadence > MAX_CADENCE:
            raise InvariantViolationError(f"cadence must be at most {MAX_CADENCE}, got {cadence}")
        return replace(
            self,
            name=self.name if name is None else name,
            cadence=self.cadence if cadence is None else cadence,
            enabled=self.enabled if enabled is None else enabled,
            paused=self.paused if paused is None else paused,
            parameters=self.parameters if parameters is None else parameters,
            updated_at=max(now, self.created_at),
        )

    def crawled(
        self,
        now: datetime,
        *,
        listed: bool,
        watermark: date | None,
        error: str,
    ) -> Self:
        """The source after a crawl. ``listed``: the crawl read the listing, so the source was
        reached (``last_fetch_at`` moves on); otherwise only the error is recorded. ``error`` is
        empty after a crawl that went well and is cut to ``MAX_ERROR_CHARS``."""
        return replace(
            self,
            last_fetch_at=now if listed else self.last_fetch_at,
            watermark=watermark_of(watermark) if listed else self.watermark,
            last_error=error.strip()[:MAX_ERROR_CHARS],
            updated_at=max(now, self.created_at),
        )

    def named(self, name: str, now: datetime) -> Self:
        """The source with ``name``, for a row stored before sources had names."""
        return replace(self, name=name, updated_at=max(now, self.updated_at))
