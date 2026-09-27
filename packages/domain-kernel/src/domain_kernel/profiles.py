"""Read model of a business profile. The BusinessProfile aggregate stays in its service."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from domain_kernel._validation import freeze_mapping, require_instance, require_int
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, TenantId


@dataclass(frozen=True, slots=True)
class ProfileSnapshot:
    """One version of a profile's attributes, as the applicability engine sees it.

    ``as_of_fy`` is the financial year the per-financial-year attributes (turnover bands) are
    stated for; the profile service assembles the snapshot for the year a rule asks about.
    """

    business_id: BusinessId
    tenant_id: TenantId
    version: int
    attributes: Mapping[str, object] = field(hash=False)
    as_of_fy: FinancialYear | None = None

    def __post_init__(self) -> None:
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_int(self.version, "version", minimum=1)
        object.__setattr__(self, "attributes", freeze_mapping(self.attributes, "attributes"))
        if self.as_of_fy is not None:
            require_instance(self.as_of_fy, FinancialYear, "as_of_fy")

    def get(self, key: str) -> object | None:
        return self.attributes.get(key)
