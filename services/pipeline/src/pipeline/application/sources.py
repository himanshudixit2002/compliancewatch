"""The source manager: the sources and their documents as the regulatory team reads them, the
sources an admin adds and edits, and the built-in sources the worker adds when it starts.

- ``SyncSources``: inserts the built-in sources the ``source`` table lacks and names a built-in
  row stored before sources had names; it changes nothing else, so an admin's edits stay.
- ``ListSources`` and ``ReadSource``: each source with its adapter type's reading of its
  parameters, how it stands (healthy, fetching, failing, paused), its freshness against its
  cadence, its document count and its latest crawl.
- ``AddSource`` and ``EditSource``: an admin's changes, with the parameters checked by the adapter
  type (``AdapterTypes``). Each writes its ``audit.event`` row, ``pipeline.source.add`` or
  ``pipeline.source.edit``, of no tenant, in the transaction of the change, with the actor, the
  reason and the source before and after.
- ``ListSourceDocuments``, ``ReadDocument`` and ``ReadRawDocument``: a source's documents a page
  at a time (newest publication first), one document, and its stored bytes read back from the raw
  store and checked against the digest its record names.

Starting a crawl by hand is ``application.crawl.StartCrawl``.
"""

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import DocumentId
from pipeline.domain.crawl import CrawlRun
from pipeline.domain.errors import (
    DocumentNotFoundError,
    RawDocumentUnreadableError,
    RawObjectCorruptError,
    RawObjectMissingError,
    RawStoreError,
    RawStoreUnavailableError,
    SourceExistsError,
    SourceInvalidError,
    SourceNotFoundError,
)
from pipeline.domain.ports import AdapterTypes, RawStore, SourceKind
from pipeline.domain.raw_documents import RawDocumentRecord
from pipeline.domain.repository import DocumentKey, UnitOfWorkFactory
from pipeline.domain.schedule import Freshness, SourceStatus, freshness_of, status_of
from pipeline.domain.sources import MAX_CADENCE, Source, SourceDefinition
from py_common.logging import get_logger

log = get_logger(__name__)

SOURCE_SUBJECT: Final = "source"
ADD_ACTION: Final = "pipeline.source.add"
EDIT_ACTION: Final = "pipeline.source.edit"
FETCH_ACTION: Final = "pipeline.source.fetch"
MIN_REASON_CHARS: Final = 10
MAX_REASON_CHARS: Final = 2_000


def require_reason(reason: str) -> str:
    """Why an admin changes a source: stripped, 10 to 2,000 characters."""
    text = reason.strip()
    if not MIN_REASON_CHARS <= len(text) <= MAX_REASON_CHARS:
        raise InvariantViolationError(
            f"a reason of {MIN_REASON_CHARS} to {MAX_REASON_CHARS} characters is required"
        )
    return text


@dataclass(frozen=True, slots=True)
class AdminAction:
    """Who changes a source and why: the actor the audit entry names, the reason, and the
    request behind it."""

    actor: AuditActor
    reason: str
    correlation_id: str | None = None


def audited(source: Source) -> dict[str, object]:
    """What an audit entry keeps of a source: what an admin may change."""
    return {
        "name": source.name,
        "adapter_type": source.adapter_type,
        "parameters": dict(source.parameters),
        "cadence_seconds": int(source.cadence.total_seconds()),
        "enabled": source.enabled,
        "paused": source.paused,
    }


def source_entry(
    action: str,
    key: str,
    admin: AdminAction,
    *,
    reason: str,
    at: datetime,
    before: Mapping[str, object] | None,
    after: Mapping[str, object] | None,
) -> AuditEntry:
    return AuditEntry(
        action=action,
        tenant_id=None,
        subject_type=SOURCE_SUBJECT,
        subject_id=key,
        actor=admin.actor,
        reason=reason,
        before=before,
        after=after,
        occurred_at=at,
        correlation_id=admin.correlation_id,
    )


@dataclass(frozen=True, slots=True)
class SyncReport:
    added: tuple[str, ...] = ()
    named: tuple[str, ...] = ()


class SyncSources:
    """Insert the built-in sources the store lacks; name a built-in row that has no name yet."""

    def __init__(
        self,
        units: UnitOfWorkFactory,
        definitions: Sequence[SourceDefinition],
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._units = units
        self._definitions = tuple(definitions)
        self._clock = clock

    def run(self) -> SyncReport:
        now = self._clock()
        added: list[str] = []
        named: list[str] = []
        with self._units() as unit:
            for definition in self._definitions:
                if unit.sources.add(Source.of(definition, now)):
                    added.append(definition.key)
                    continue
                stored = unit.sources.get(definition.key)
                if stored is not None and not stored.name and definition.name:
                    unit.sources.save(stored.named(definition.name, now))
                    named.append(definition.key)
        if added or named:
            log.info("pipeline.sources_synced", added=added, named=named)
        return SyncReport(tuple(added), tuple(named))


@dataclass(frozen=True, slots=True)
class SourceView:
    """A source as the API shows it. ``kind`` is None for a row whose adapter type the code
    lacks or whose parameters it refuses (the crawl fails on it, which ``last_error`` says)."""

    source: Source
    kind: SourceKind | None
    status: SourceStatus
    freshness: Freshness
    document_count: int
    latest_run: CrawlRun | None


class ListSources:
    def __init__(
        self,
        units: UnitOfWorkFactory,
        types: AdapterTypes,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._units = units
        self._types = types
        self._clock = clock

    def run(self) -> list[SourceView]:
        with self._units() as unit:
            sources = unit.sources.list()
            counts = unit.documents.counts()
            latest = unit.crawl_runs.latest_by_source()
        now = self._clock()
        return [
            self._view(source, counts.get(source.key, 0), latest.get(source.key), now)
            for source in sources
        ]

    def one(self, key: str) -> SourceView:
        with self._units() as unit:
            source = unit.sources.get(key)
            if source is None:
                raise SourceNotFoundError(f"no source has the key {key!r}")
            count = unit.documents.counts().get(key, 0)
            latest = unit.crawl_runs.latest(key)
        return self._view(source, count, latest, self._clock())

    def _view(
        self, source: Source, count: int, latest: CrawlRun | None, now: datetime
    ) -> SourceView:
        try:
            kind: SourceKind | None = self._types.describe(source.adapter_type, source.parameters)
        except SourceInvalidError:
            kind = None
        return SourceView(
            source=source,
            kind=kind,
            status=status_of(source, latest, now),
            freshness=freshness_of(source, now),
            document_count=count,
            latest_run=latest,
        )


def _require_cadence(cadence: timedelta) -> timedelta:
    if cadence > MAX_CADENCE:
        raise InvariantViolationError(f"cadence must be at most {MAX_CADENCE}, got {cadence}")
    return cadence


@dataclass(frozen=True, slots=True)
class NewSource:
    key: str
    name: str
    adapter_type: str
    parameters: Mapping[str, object]
    cadence: timedelta
    enabled: bool = True
    paused: bool = False


class AddSource:
    def __init__(
        self,
        units: UnitOfWorkFactory,
        types: AdapterTypes,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._units = units
        self._types = types
        self._clock = clock

    def run(self, new: NewSource, admin: AdminAction) -> Source:
        reason = require_reason(admin.reason)
        kind = self._types.describe(new.adapter_type, new.parameters)
        now = self._clock()
        source = Source(
            key=new.key,
            adapter_type=kind.adapter_type,
            parameters=kind.parameters,
            cadence=_require_cadence(new.cadence),
            created_at=now,
            updated_at=now,
            enabled=new.enabled,
            paused=new.paused,
            name=new.name,
        )
        with self._units() as unit:
            if not unit.sources.add(source):
                raise SourceExistsError(f"a source with the key {new.key!r} exists already")
            unit.audit.write(
                source_entry(
                    ADD_ACTION,
                    source.key,
                    admin,
                    reason=reason,
                    at=now,
                    before=None,
                    after=audited(source),
                )
            )
        log.info("pipeline.source_added", source=source.key, adapter_type=source.adapter_type)
        return source


@dataclass(frozen=True, slots=True)
class SourceEdit:
    """What an admin changes; None leaves a field as it is."""

    name: str | None = None
    cadence: timedelta | None = None
    enabled: bool | None = None
    paused: bool | None = None
    parameters: Mapping[str, object] | None = None


class EditSource:
    """Change a source's name, cadence, switches or parameters. An edit that changes nothing
    writes nothing."""

    def __init__(
        self,
        units: UnitOfWorkFactory,
        types: AdapterTypes,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._units = units
        self._types = types
        self._clock = clock

    def run(self, key: str, edit: SourceEdit, admin: AdminAction) -> Source:
        reason = require_reason(admin.reason)
        now = self._clock()
        with self._units() as unit:
            before = unit.sources.get(key, for_update=True)
            if before is None:
                raise SourceNotFoundError(f"no source has the key {key!r}")
            parameters = (
                None
                if edit.parameters is None
                else self._types.describe(before.adapter_type, edit.parameters).parameters
            )
            after = before.edited(
                now,
                name=edit.name,
                cadence=edit.cadence,
                enabled=edit.enabled,
                paused=edit.paused,
                parameters=parameters,
            )
            if audited(after) == audited(before):
                return before
            unit.sources.save(after)
            unit.audit.write(
                source_entry(
                    EDIT_ACTION,
                    key,
                    admin,
                    reason=reason,
                    at=now,
                    before=audited(before),
                    after=audited(after),
                )
            )
        log.info("pipeline.source_edited", source=key)
        return after


class ListSourceDocuments:
    def __init__(self, units: UnitOfWorkFactory) -> None:
        self._units = units

    def run(
        self, key: str, *, after: DocumentKey | None, limit: int
    ) -> Sequence[RawDocumentRecord]:
        with self._units() as unit:
            if unit.sources.get(key) is None:
                raise SourceNotFoundError(f"no source has the key {key!r}")
            return unit.documents.page(key, after=after, limit=limit)


class ReadDocument:
    def __init__(self, units: UnitOfWorkFactory) -> None:
        self._units = units

    def run(self, document_id: DocumentId) -> RawDocumentRecord:
        with self._units() as unit:
            record = unit.documents.get(document_id)
        if record is None:
            raise DocumentNotFoundError(f"no stored document has the id {document_id}")
        return record


@dataclass(frozen=True, slots=True)
class RawFile:
    record: RawDocumentRecord
    content: bytes


class ReadRawDocument:
    """The document's bytes from the raw store, read with no transaction open and served only
    when their SHA-256 is the record's."""

    def __init__(self, units: UnitOfWorkFactory, raw_store: RawStore) -> None:
        self._read = ReadDocument(units)
        self._raw = raw_store

    def run(self, document_id: DocumentId) -> RawFile:
        record = self._read.run(document_id)
        try:
            content = self._raw.get(record.storage_key)
        except (RawObjectMissingError, RawObjectCorruptError, ValueError) as exc:
            log.error(
                "pipeline.raw_document_unreadable",
                document_id=str(document_id),
                storage_key=record.storage_key,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise RawDocumentUnreadableError(
                f"document {document_id}: the raw store cannot serve {record.storage_key}"
            ) from exc
        except RawStoreError as exc:
            raise RawStoreUnavailableError(f"the raw store did not answer: {exc}") from exc
        if hashlib.sha256(content).hexdigest() != record.sha256:
            log.error(
                "pipeline.raw_document_unreadable",
                document_id=str(document_id),
                storage_key=record.storage_key,
                error="digest mismatch",
            )
            raise RawDocumentUnreadableError(
                f"document {document_id}: the stored bytes have another digest than its record"
            )
        return RawFile(record, content)
