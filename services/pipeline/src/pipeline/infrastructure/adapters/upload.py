"""Sources whose documents are uploaded: the adapter of the upload-only type.

Some documents the rules rest on are not listed by any site the pipeline reads: the statutes (the
CGST Act, the CGST Rules, the IGST Act) that the rules and notifications cite. A source of the
``upload`` type holds them. It lists nothing, so the schedule never crawls it, and fetches
nothing; an analyst uploads each document (``POST /v1/pipeline/sources/{key}/uploads``).
"""

from collections.abc import Iterable
from datetime import datetime

from domain_kernel.documents import DiscoveredDocument, DocumentRef, RawDocument
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import SourceId


class UploadOnlyAdapter:
    def __init__(self, source_id: SourceId) -> None:
        self._source_id = source_id

    def list_documents(self, since: datetime) -> Iterable[DiscoveredDocument]:
        return ()

    def fetch(self, ref: DocumentRef) -> RawDocument:
        raise InvariantViolationError(
            f"source {self._source_id} is upload-only: nothing is fetched from it, its "
            "documents are uploaded"
        )
