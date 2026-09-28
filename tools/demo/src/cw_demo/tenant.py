"""The demo tenant's facts. Made up; the GSTIN and PAN are the profile service's test values."""

from datetime import date

from domain_kernel.ids import TenantId, UserId

TENANT_ID = TenantId.new()
OWNER_ID = UserId.new()
OWNER_PHONE = "919876543210"
NOTICE_VERSION = "0.1-draft"
GSTIN = "29ABCDE1234F1Z5"
ENTITY_NAME = "Acme Traders Private Limited"
REGISTRATION_NAME = "Acme Bengaluru"
AS_OF = date(2026, 9, 28)
ATTRIBUTES: dict[str, object] = {
    "state_codes": ["29"],
    "business_category": "wholesale_trade",
    "turnover_band": "2_crore_to_5_crore",
    "peak_turnover_band": "2_crore_to_5_crore",
    "employee_count": 12,
    "supply_type": "goods",
    "filing_scheme": "regular_monthly",
    "return_filing_frequency": "monthly",
    "makes_inter_state_supplies": True,
    "makes_zero_rated_supplies": False,
    "ecommerce_role": "none",
    "pays_reverse_charge": False,
    "generates_eway_bills": True,
}
"""Attributes the owner answers during onboarding; the GSTIN lookup pre-fills the rest."""
