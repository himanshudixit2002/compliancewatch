"""The sources the store holds, as the activities read them, and the adapter types as the API
checks them.

``StoreCatalog`` is the worker's ``SourceCatalog``: it finds a source's row in the store by the
source's id (UUID v5 of its key) and builds its adapter from the row's adapter type and
parameters through ``ADAPTER_TYPES[...].validated()``, all over one polite client, so the
per-host delay holds across sources and activities. An adapter is built once and built again
only when its row's type or parameters change, so an admin's edit takes effect at the next
activity. A row whose type the code does not have, or whose parameters the type refuses, is an
``UnknownSourceError``, which no retry fixes.

``RegistryAdapterTypes`` is the API's ``AdapterTypes``: it checks a new or edited source's
parameters against its type and says what regulator, site and document type they give.
"""

import json
import threading
from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from domain_kernel.ids import SourceId
from pipeline.domain.errors import SourceInvalidError, UnknownSourceError
from pipeline.domain.ports import ResolvedSource, SourceKind
from pipeline.domain.repository import UnitOfWorkFactory
from pipeline.domain.sources import Source, SourceDefinition, source_id_of
from pipeline.infrastructure.adapters.registry import ADAPTER_TYPES, AdapterType, Parameters
from pipeline.infrastructure.http import PoliteClient


def _fingerprint(adapter_type: str, parameters: Parameters) -> str:
    return json.dumps(
        [adapter_type, parameters.model_dump(mode="json")], sort_keys=True, separators=(",", ":")
    )


class StoreCatalog:
    """The store's sources by id; ``types`` replaces the registry's adapter types (tests add a
    recorded one)."""

    def __init__(
        self,
        units: UnitOfWorkFactory,
        client: PoliteClient,
        *,
        types: Mapping[str, AdapterType] = ADAPTER_TYPES,
    ) -> None:
        self._units = units
        self._client = client
        self._types = types
        self._resolved: dict[str, tuple[str, ResolvedSource]] = {}
        self._lock = threading.Lock()

    def resolve(self, source_id: SourceId) -> ResolvedSource:
        with self._units() as unit:
            rows = unit.sources.list()
        for row in rows:
            if source_id_of(row.key) == source_id:
                return self._resolve_row(row)
        raise UnknownSourceError(f"no stored source has the id {source_id}")

    def _resolve_row(self, row: Source) -> ResolvedSource:
        kind = self._types.get(row.adapter_type)
        if kind is None:
            raise UnknownSourceError(
                f"source {row.key}: the code has no adapter type {row.adapter_type!r}"
            )
        try:
            parameters = kind.validated(row.parameters)
        except ValueError as exc:
            raise UnknownSourceError(
                f"source {row.key}: adapter type {row.adapter_type} refuses its parameters: {exc}"
            ) from exc
        fingerprint = _fingerprint(row.adapter_type, parameters)
        with self._lock:
            cached = self._resolved.get(row.key)
            if cached is not None and cached[0] == fingerprint:
                adapter = cached[1].adapter
            else:
                adapter = kind.build(self._client, source_id_of(row.key), parameters)
            resolved = ResolvedSource(
                source_id_of(row.key),
                SourceDefinition(
                    key=row.key,
                    adapter_type=row.adapter_type,
                    parameters=parameters.model_dump(mode="json"),
                    cadence=row.cadence,
                    regulator=kind.regulator,
                    doc_type=kind.doc_type(parameters),
                    name=row.name,
                ),
                adapter,
            )
            self._resolved[row.key] = (fingerprint, resolved)
            return resolved


class RegistryAdapterTypes:
    """``AdapterTypes`` over the registry's types (``types`` replaces them in tests)."""

    def __init__(self, types: Mapping[str, AdapterType] = ADAPTER_TYPES) -> None:
        self._types = types

    def names(self) -> Sequence[str]:
        return sorted(self._types)

    def describe(self, adapter_type: str, parameters: Mapping[str, object]) -> SourceKind:
        kind = self._types.get(adapter_type)
        if kind is None:
            raise SourceInvalidError(
                f"unknown adapter type {adapter_type!r}; known: {', '.join(self.names())}"
            )
        try:
            read = kind.validated(parameters)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(part) for part in error['loc']) or 'parameters'}: {error['msg']}"
                for error in exc.errors(include_url=False)
            )
            raise SourceInvalidError(
                f"adapter type {adapter_type} refuses the parameters: {problems}"
            ) from exc
        except ValueError as exc:
            raise SourceInvalidError(
                f"adapter type {adapter_type} refuses the parameters: {exc}"
            ) from exc
        return SourceKind(
            adapter_type=adapter_type,
            parameters=read.model_dump(mode="json"),
            regulator=kind.regulator,
            site=kind.site,
            doc_type=kind.doc_type(read),
        )
