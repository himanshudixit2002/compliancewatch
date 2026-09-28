"""Events the profile service publishes; payload fields follow packages/contracts/events."""

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from domain_kernel._validation import require_instance, require_int, require_text
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, UserId


class ChangeSource(StrEnum):
    """Where a profile change came from; the contract's vocabulary."""

    USER_INPUT = "user_input"
    GSTIN_LOOKUP = "gstin_lookup"
    PARTNER_API = "partner_api"
    IMPORT = "import"


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileUpdated(DomainEvent):
    topic: ClassVar[str] = "profile.updated"
    schema_version: ClassVar[str] = "1.0.0"

    business_id: BusinessId
    profile_version: int
    changed_attributes: tuple[str, ...]
    ontology_version: str
    source: ChangeSource
    changed_by: UserId | None = None

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        require_instance(self.business_id, BusinessId, "business_id")
        require_int(self.profile_version, "profile_version", minimum=1)
        changed = require_instance(self.changed_attributes, tuple, "changed_attributes")
        if not changed:
            raise ValueError("changed_attributes must name at least one attribute")
        for key in changed:
            require_text(key, "changed_attributes[]")
        require_text(self.ontology_version, "ontology_version")
        require_instance(self.source, ChangeSource, "source")
        if self.changed_by is not None:
            require_instance(self.changed_by, UserId, "changed_by")
