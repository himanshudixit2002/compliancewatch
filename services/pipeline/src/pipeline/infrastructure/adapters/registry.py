"""Adapter types, the built-in sources, their stable ids, and how to build each adapter.

An adapter type (``ADAPTER_TYPES``) reads one regulator site: its name, the regulator, the site,
the parameters it takes (a pydantic model that refuses anything else) and how it builds the
adapter. A source (``SourceSpec``) is a key, an adapter type with its parameters, and how often
it is read; its regulator and document type follow from the type and the parameters. The CBIC
type reads both portal listings, with the listing and the category as parameters; a category
needs its recorded listing (``cbic.RECORDED_CATEGORIES``).

A source id is derived from its key with UUID v5, so the same source has the same id in every
environment and a fixture recorded for ``cbic_notifications`` matches the adapter that replays
it. ``RegistryCatalog`` serves the built-in sources to the activities by id
(``pipeline.domain.ports.SourceCatalog``).
"""

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final, Literal, Self
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, model_validator

from domain_kernel.documents import DocumentType
from domain_kernel.ids import SourceId
from domain_kernel.protocols import SourceAdapter
from pipeline.domain.errors import UnknownSourceError
from pipeline.domain.ports import ResolvedSource
from pipeline.domain.sources import SourceDefinition
from pipeline.infrastructure.adapters.cbic import RECORDED_CATEGORIES, CbicAdapter
from pipeline.infrastructure.adapters.gstcouncil import GstCouncilAdapter
from pipeline.infrastructure.adapters.gstn import GstnAdapter
from pipeline.infrastructure.adapters.mahagst import MahagstAdapter
from pipeline.infrastructure.http import PoliteClient

SOURCE_NAMESPACE = "https://compliancewatch.invalid/sources/"


def source_id_for(key: str) -> SourceId:
    return SourceId(uuid5(NAMESPACE_URL, SOURCE_NAMESPACE + key))


class Parameters(BaseModel):
    """An adapter type's parameters: frozen, and nothing the type does not name."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CbicParameters(Parameters):
    listing: Literal["notifications", "circulars"]
    category: str

    @model_validator(mode="after")
    def _recorded_category(self) -> Self:
        recorded = RECORDED_CATEGORIES[self.listing]
        if self.category not in recorded:
            raise ValueError(
                f"CBIC {self.listing} category {self.category!r} has no recorded listing; "
                f"recorded: {', '.join(recorded)}"
            )
        return self


@dataclass(frozen=True, slots=True)
class AdapterType:
    name: str
    regulator: str
    site: str
    parameters: type[Parameters]
    build: Callable[[PoliteClient, SourceId, Any], SourceAdapter]
    """Builds the adapter from the client, the source id and the validated parameters."""
    doc_type: Callable[[Any], DocumentType]

    def validated(self, parameters: Mapping[str, object]) -> Parameters:
        """The parameters as this type reads them; ``ValueError`` (pydantic's) when they are
        not."""
        return self.parameters.model_validate(dict(parameters))


def _cbic(client: PoliteClient, source_id: SourceId, parameters: CbicParameters) -> CbicAdapter:
    return CbicAdapter(client, source_id, listing=parameters.listing, category=parameters.category)


def _cbic_doc_type(parameters: CbicParameters) -> DocumentType:
    return DocumentType.CIRCULAR if parameters.listing == "circulars" else DocumentType.NOTIFICATION


ADAPTER_TYPES: Final[Mapping[str, AdapterType]] = {
    kind.name: kind
    for kind in (
        AdapterType(
            "cbic",
            "CBIC",
            "taxinformation.cbic.gov.in",
            CbicParameters,
            _cbic,
            _cbic_doc_type,
        ),
        AdapterType(
            "gstcouncil",
            "GST Council",
            "gstcouncil.gov.in",
            Parameters,
            lambda client, source_id, _: GstCouncilAdapter(client, source_id),
            lambda _: DocumentType.PRESS_RELEASE,
        ),
        AdapterType(
            "gstn",
            "GSTN",
            "gst.gov.in",
            Parameters,
            lambda client, source_id, _: GstnAdapter(client, source_id),
            lambda _: DocumentType.PRESS_RELEASE,
        ),
        AdapterType(
            "mahagst",
            "Maharashtra GST",
            "mahagst.gov.in",
            Parameters,
            lambda client, source_id, _: MahagstAdapter(client, source_id),
            lambda _: DocumentType.NOTIFICATION,
        ),
    )
}


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """A built-in source: its key, its adapter type with the type's parameters, and its
    cadence."""

    key: str
    adapter_type: str
    parameters: Mapping[str, object]
    cadence: timedelta

    def __post_init__(self) -> None:
        if self.adapter_type not in ADAPTER_TYPES:
            raise ValueError(
                f"{self.key}: unknown adapter type {self.adapter_type!r}; "
                f"known: {', '.join(sorted(ADAPTER_TYPES))}"
            )
        self.kind.validated(self.parameters)

    @property
    def kind(self) -> AdapterType:
        return ADAPTER_TYPES[self.adapter_type]

    @property
    def regulator(self) -> str:
        return self.kind.regulator

    @property
    def doc_type(self) -> DocumentType:
        return self.kind.doc_type(self.kind.validated(self.parameters))

    @property
    def site(self) -> str:
        return self.kind.site

    @property
    def source_id(self) -> SourceId:
        return source_id_for(self.key)

    def definition(self) -> SourceDefinition:
        return SourceDefinition(
            key=self.key,
            adapter_type=self.adapter_type,
            parameters=self.kind.validated(self.parameters).model_dump(mode="json"),
            cadence=self.cadence,
            regulator=self.regulator,
            doc_type=self.doc_type,
        )

    def build(self, client: PoliteClient) -> SourceAdapter:
        return self.kind.build(client, self.source_id, self.kind.validated(self.parameters))


SOURCES: Final[Mapping[str, SourceSpec]] = {
    spec.key: spec
    for spec in (
        SourceSpec(
            "cbic_notifications",
            "cbic",
            {"listing": "notifications", "category": "Central Tax"},
            timedelta(hours=2),
        ),
        SourceSpec(
            "cbic_circulars",
            "cbic",
            {"listing": "circulars", "category": "Circulars CGST"},
            timedelta(hours=6),
        ),
        SourceSpec("gstcouncil_press", "gstcouncil", {}, timedelta(hours=6)),
        SourceSpec("gstn_advisories", "gstn", {}, timedelta(hours=3)),
        SourceSpec("mahagst_notifications", "mahagst", {}, timedelta(hours=12)),
    )
}


def build_adapter(key: str, client: PoliteClient) -> SourceAdapter:
    spec = SOURCES.get(key)
    if spec is None:
        raise KeyError(f"unknown source {key!r}; known: {', '.join(sorted(SOURCES))}")
    return spec.build(client)


class RegistryCatalog:
    """The built-in sources by id, each adapter built once on first use, every one over the
    same polite client, so the per-host delay holds across sources and activities."""

    def __init__(self, client: PoliteClient, sources: Mapping[str, SourceSpec] = SOURCES) -> None:
        self._client = client
        self._specs = {spec.source_id: spec for spec in sources.values()}
        self._resolved: dict[SourceId, ResolvedSource] = {}
        self._lock = threading.Lock()

    def resolve(self, source_id: SourceId) -> ResolvedSource:
        with self._lock:
            found = self._resolved.get(source_id)
            if found is None:
                spec = self._specs.get(source_id)
                if spec is None:
                    raise UnknownSourceError(f"no source has the id {source_id}")
                found = ResolvedSource(source_id, spec.definition(), spec.build(self._client))
                self._resolved[source_id] = found
            return found
