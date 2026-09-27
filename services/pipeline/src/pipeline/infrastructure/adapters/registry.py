"""Which sources exist, their stable ids, and how to build each adapter.

A source id is derived from its key with UUID v5, so the same source has the same id in every
environment and a fixture recorded for ``cbic_notifications`` matches the adapter that replays
it. New sources are added here and nowhere else.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from domain_kernel.documents import DocumentType
from domain_kernel.ids import SourceId
from domain_kernel.protocols import SourceAdapter
from pipeline.infrastructure.adapters.cbic import CbicCircularsAdapter, CbicNotificationsAdapter
from pipeline.infrastructure.adapters.gstcouncil import GstCouncilAdapter
from pipeline.infrastructure.adapters.gstn import GstnAdapter
from pipeline.infrastructure.adapters.mahagst import MahagstAdapter
from pipeline.infrastructure.http import PoliteClient

SOURCE_NAMESPACE = "https://compliancewatch.invalid/sources/"


def source_id_for(key: str) -> SourceId:
    return SourceId(uuid5(NAMESPACE_URL, SOURCE_NAMESPACE + key))


@dataclass(frozen=True, slots=True)
class SourceSpec:
    key: str
    regulator: str
    doc_type: DocumentType
    site: str
    build: Callable[[PoliteClient, SourceId], SourceAdapter]

    @property
    def source_id(self) -> SourceId:
        return source_id_for(self.key)


SOURCES: Mapping[str, SourceSpec] = {
    spec.key: spec
    for spec in (
        SourceSpec(
            "cbic_notifications",
            "CBIC",
            DocumentType.NOTIFICATION,
            "taxinformation.cbic.gov.in",
            CbicNotificationsAdapter,
        ),
        SourceSpec(
            "cbic_circulars",
            "CBIC",
            DocumentType.CIRCULAR,
            "taxinformation.cbic.gov.in",
            CbicCircularsAdapter,
        ),
        SourceSpec(
            "gstcouncil_press",
            "GST Council",
            DocumentType.PRESS_RELEASE,
            "gstcouncil.gov.in",
            GstCouncilAdapter,
        ),
        SourceSpec(
            "gstn_advisories", "GSTN", DocumentType.PRESS_RELEASE, "gst.gov.in", GstnAdapter
        ),
        SourceSpec(
            "mahagst_notifications",
            "Maharashtra GST",
            DocumentType.NOTIFICATION,
            "mahagst.gov.in",
            MahagstAdapter,
        ),
    )
}


def build_adapter(key: str, client: PoliteClient) -> SourceAdapter:
    spec = SOURCES.get(key)
    if spec is None:
        raise KeyError(f"unknown source {key!r}; known: {', '.join(sorted(SOURCES))}")
    return spec.build(client, spec.source_id)
