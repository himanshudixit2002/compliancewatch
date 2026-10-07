"""Where a page of a tenant's data export starts: keyset pagination, oldest first.

Each export section is read ``EXPORT_PAGE_SIZE`` rows at a time, ordered by a time and then the
row's id, and the next page starts after the last row of the previous one, so a page costs the
same however deep the export is.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from domain_kernel._validation import require_aware, require_instance

EXPORT_PAGE_SIZE: Final = 500


@dataclass(frozen=True, slots=True)
class ExportAfter:
    """After the row at ``at`` with the id ``id``."""

    at: datetime
    id: UUID

    def __post_init__(self) -> None:
        require_aware(self.at, "at")
        require_instance(self.id, UUID, "id")
