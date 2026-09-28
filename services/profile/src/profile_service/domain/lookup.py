"""The GSTIN lookup at the boundary: what a registry answer looks like, whoever provides it.

A real provider (the GSTN sanctioned API through a GSP, or an aggregator: an open question in
the roadmap that needs an account) sits behind ``GstinLookupProvider``. When no provider is
configured, or the provider is down, ``lookup`` returns None and the user proceeds manually;
the profile opens a review task to re-verify later (guide section 7, profile-service).
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from domain_kernel._validation import require_instance, require_text
from domain_kernel.identifiers import Gstin


@dataclass(frozen=True, slots=True)
class GstinLookupResult:
    """What the registry says about a GSTIN, already in the ontology's vocabulary."""

    gstin: Gstin
    legal_name: str
    trade_name: str = ""
    registration_type: str = ""
    """An ontology ``registration_type`` value or empty when the registry's code is unmapped."""
    gstin_status: str = ""
    state_code: str = ""
    constitution: str = ""
    registered_since: date | None = None

    def __post_init__(self) -> None:
        require_instance(self.gstin, Gstin, "gstin")
        require_text(self.legal_name, "legal_name")

    def attribute_values(self) -> dict[str, object]:
        """The profile attributes the answer fills, keyed by ontology attribute."""
        values: dict[str, object] = {}
        if self.registration_type:
            values["registration_type"] = self.registration_type
        if self.gstin_status:
            values["gstin_status"] = self.gstin_status
        if self.constitution:
            values["constitution"] = self.constitution
        if self.registered_since is not None:
            values["registered_since"] = self.registered_since.isoformat()
        return values


class GstinLookupProvider(Protocol):
    def lookup(self, gstin: Gstin) -> GstinLookupResult | None:
        """The registry's answer, or None when the provider has nothing or is unavailable."""
        ...
