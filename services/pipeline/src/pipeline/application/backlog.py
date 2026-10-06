"""The classified backlog: documents that wait as ``classified`` with no extraction stored for the
current prompt, such as the ones the ingest classified while ``CW_PIPELINE_EXTRACTION_ENABLED``
was off (turning it on extracts none of them by itself).

``ExtractionBacklog`` counts them per source and gives the extraction request of each, as the
ingest would hand it to its extraction: the document, its source with the source's regulator, the
type its classification gives, and its own reference. A document already extracted for the
current prompt is not in the backlog, and neither is one of a source the code cannot read.
``pipeline-extract-backlog`` (``pipeline.backlog``) starts the sweep that extracts them
(``workflows.extract_backlog``).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from pipeline.application.extraction import RULE_PROMPT_REF, ExtractionRequest
from pipeline.domain.classification import Route
from pipeline.domain.errors import SourceInvalidError
from pipeline.domain.ports import AdapterTypes, SourceKind
from pipeline.domain.repository import UnitOfWorkFactory
from pipeline.domain.sources import source_id_of

MAX_BATCH: Final = 1_000
"""The most documents one sweep extracts; a larger backlog takes another sweep."""


@dataclass(frozen=True, slots=True)
class Backlog:
    """The documents a sweep would extract (``requests``, at most its limit, the first fetched
    first), and how many wait per source in all."""

    requests: tuple[ExtractionRequest, ...]
    waiting: Mapping[str, int]

    @property
    def total(self) -> int:
        return sum(self.waiting.values())


class ExtractionBacklog:
    def __init__(self, units: UnitOfWorkFactory, types: AdapterTypes) -> None:
        self._units = units
        self._types = types

    def run(self, *, source_key: str | None = None, limit: int = MAX_BATCH) -> Backlog:
        """The backlog of one source or every one, and the requests of at most ``limit`` of its
        documents."""
        bounded = max(1, min(limit, MAX_BATCH))
        with self._units() as unit:
            waiting = {
                key: count
                for key, count in unit.documents.awaiting_counts(RULE_PROMPT_REF).items()
                if source_key in (None, key)
            }
            records = unit.documents.awaiting_extraction(
                RULE_PROMPT_REF, source_key=source_key, limit=bounded
            )
            classifications = unit.classifications.of_documents(
                [record.document_id for record in records]
            )
            kinds = {
                source.key: self._kind(source.adapter_type, source.parameters)
                for source in unit.sources.list()
            }
        requests: list[ExtractionRequest] = []
        for record in records:
            classification = classifications.get(record.document_id)
            kind = kinds.get(record.source_key)
            if classification is None or classification.route is not Route.EXTRACT or kind is None:
                continue
            requests.append(
                ExtractionRequest(
                    document_id=record.document_id.value,
                    source_id=source_id_of(record.source_key).value,
                    source_key=record.source_key,
                    regulator=kind.regulator,
                    doc_type=classification.doc_type,
                    own_ref=record.external_ref,
                )
            )
        return Backlog(tuple(requests), waiting)

    def _kind(self, adapter_type: str, parameters: Mapping[str, object]) -> SourceKind | None:
        try:
            return self._types.describe(adapter_type, parameters)
        except SourceInvalidError:
            return None
