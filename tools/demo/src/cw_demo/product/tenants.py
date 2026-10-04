"""The synthetic tenants ``cw-product seed`` creates in the local product.

Two tenants with fixed ids, so seeding again finds what it made the first time:

- ``BUSINESS_TENANT``, a business with one registration that files GSTR-3B monthly, made from
  the profile service's demo GSTIN (the static lookup pre-fills it);
- ``CA_FIRM_TENANT``, a CA firm with two clients that file quarterly, one in Karnataka (group A
  of the quarterly return) from the same demo GSTIN, one in Delhi (group B) from a made-up GSTIN
  the lookup does not know, which opens a verify_registration task as any unknown GSTIN does.

Every name says it is synthetic. The phone numbers are +91 followed by zeros, which no Indian
mobile number starts with, and the mailboxes are on ``.invalid``, a domain reserved never to
exist; nothing is ever sent to them anyway, since the local product delivers through the sink.
``expected`` is what each registration's answers make of the four seed rules the golden world
cites: the check compares the engine's decisions with it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal
from uuid import UUID

TenantKind = Literal["business", "ca_firm"]
RecipientRole = Literal["owner", "ca_admin"]

APPLIES: Final = "applies"
NOT_APPLICABLE: Final = "not_applicable"
DEMO_GSTIN: Final = "29ABCDE1234F1Z5"
"""The profile service's static lookup knows this one (``DEMO_LOOKUPS``)."""
MADE_UP_DELHI_GSTIN: Final = "07ZZZZZ9999Z1Z5"
"""No lookup knows it: the prefill opens a verify_registration task instead."""


@dataclass(frozen=True, slots=True)
class SyntheticBusiness:
    """One legal entity with one GSTIN registration, and the owner's answers on each node.
    ``per_year`` names the entity answers that are given for a financial year."""

    key: str
    name: str
    registration_name: str
    gstin: str
    entity_answers: Mapping[str, object]
    registration_answers: Mapping[str, object]
    expected: Mapping[str, str]
    per_year: frozenset[str] = frozenset({"turnover_band"})


@dataclass(frozen=True, slots=True)
class SyntheticTenant:
    """A tenant with the person who consents for it and hears from it: the owner of a business,
    or the admin of a CA firm, who hears about every client in the firm's daily digest."""

    key: str
    tenant_id: UUID
    kind: TenantKind
    name: str
    owner_id: UUID
    owner_name: str
    recipient_id: UUID
    role: RecipientRole
    phone: str
    email: str
    businesses: tuple[SyntheticBusiness, ...]

    def business(self, key: str) -> SyntheticBusiness:
        for business in self.businesses:
            if business.key == key:
                return business
        raise KeyError(f"{self.key} has no business {key!r}")


def _frozen[V](values: Mapping[str, V]) -> Mapping[str, V]:
    return MappingProxyType(dict(values))


MONTHLY_FILER: Final = _frozen(
    {
        "supply_type": "goods",
        "filing_scheme": "regular_monthly",
        "return_filing_frequency": "monthly",
        "makes_inter_state_supplies": True,
        "makes_zero_rated_supplies": False,
        "ecommerce_role": "none",
        "pays_reverse_charge": False,
        "generates_eway_bills": True,
    }
)
"""The answers of ``apps/web/scripts/seed`` (``DEMO.registrationAttributes``)."""

BUSINESS_TENANT: Final = SyntheticTenant(
    key="business",
    tenant_id=UUID("00000000-0000-4000-8000-0000000d0001"),
    kind="business",
    name="Demo Traders (synthetic)",
    owner_id=UUID("00000000-0000-4000-8000-0000000d0101"),
    owner_name="Demo owner (synthetic)",
    recipient_id=UUID("00000000-0000-4000-8000-0000000d0201"),
    role="owner",
    phone="+910000000001",
    email="owner@demo-traders.invalid",
    businesses=(
        SyntheticBusiness(
            key="demo_traders",
            name="Demo Traders (synthetic)",
            registration_name="Demo Traders Bengaluru (synthetic)",
            gstin=DEMO_GSTIN,
            entity_answers=_frozen(
                {
                    "state_codes": ["29"],
                    "business_category": "wholesale_trade",
                    "turnover_band": "2_crore_to_5_crore",
                    "peak_turnover_band": "2_crore_to_5_crore",
                    "employee_count": 12,
                }
            ),
            registration_answers=MONTHLY_FILER,
            expected=_frozen(
                {
                    "gstr3b_monthly": APPLIES,
                    "gstr3b_quarterly_group_a": NOT_APPLICABLE,
                    "gstr3b_quarterly_group_b": NOT_APPLICABLE,
                    "gstr9_annual": APPLIES,
                }
            ),
        ),
    ),
)

CA_FIRM_TENANT: Final = SyntheticTenant(
    key="ca_firm",
    tenant_id=UUID("00000000-0000-4000-8000-0000000d0002"),
    kind="ca_firm",
    name="Demo CA Associates (synthetic)",
    owner_id=UUID("00000000-0000-4000-8000-0000000d0102"),
    owner_name="Demo CA admin (synthetic)",
    recipient_id=UUID("00000000-0000-4000-8000-0000000d0202"),
    role="ca_admin",
    phone="+910000000002",
    email="admin@demo-ca-associates.invalid",
    businesses=(
        SyntheticBusiness(
            key="client_karnataka",
            name="Demo Client One (synthetic)",
            registration_name="Demo Client One Bengaluru (synthetic)",
            gstin=DEMO_GSTIN,
            entity_answers=_frozen(
                {
                    "state_codes": ["29"],
                    "business_category": "retail_trade",
                    "turnover_band": "75_lakh_to_1_5_crore",
                    "peak_turnover_band": "75_lakh_to_1_5_crore",
                    "employee_count": 4,
                }
            ),
            registration_answers=_frozen(
                {
                    "supply_type": "goods",
                    "filing_scheme": "regular_qrmp",
                    "return_filing_frequency": "quarterly",
                }
            ),
            expected=_frozen(
                {
                    "gstr3b_monthly": NOT_APPLICABLE,
                    "gstr3b_quarterly_group_a": APPLIES,
                    "gstr3b_quarterly_group_b": NOT_APPLICABLE,
                    "gstr9_annual": NOT_APPLICABLE,
                }
            ),
        ),
        SyntheticBusiness(
            key="client_delhi",
            name="Demo Client Two (synthetic)",
            registration_name="Demo Client Two Delhi (synthetic)",
            gstin=MADE_UP_DELHI_GSTIN,
            entity_answers=_frozen(
                {
                    "state_codes": ["07"],
                    "business_category": "services",
                    "turnover_band": "40_lakh_to_75_lakh",
                    "peak_turnover_band": "40_lakh_to_75_lakh",
                    "employee_count": 2,
                }
            ),
            registration_answers=_frozen(
                {
                    "registration_type": "regular",
                    "supply_type": "services",
                    "filing_scheme": "regular_qrmp",
                    "return_filing_frequency": "quarterly",
                }
            ),
            expected=_frozen(
                {
                    "gstr3b_monthly": NOT_APPLICABLE,
                    "gstr3b_quarterly_group_a": NOT_APPLICABLE,
                    "gstr3b_quarterly_group_b": APPLIES,
                    "gstr9_annual": NOT_APPLICABLE,
                }
            ),
        ),
    ),
)

TENANTS: Final = (BUSINESS_TENANT, CA_FIRM_TENANT)


def tenant_named(key: str) -> SyntheticTenant:
    for tenant in TENANTS:
        if tenant.key == key:
            return tenant
    raise KeyError(f"no synthetic tenant {key!r}; there are {[t.key for t in TENANTS]}")
