# Changelog

Versions follow semver. A new attribute or allowed value is a minor bump, a removed or renamed
one is a major bump, wording is a patch.

## 0.1.0 - 2026-09-27

First release. Sixteen GST attributes: registration_type, gstin_status, registered_since,
state_codes, constitution, business_category, supply_type, turnover_band, peak_turnover_band,
return_filing_frequency, makes_inter_state_supplies, makes_zero_rated_supplies, ecommerce_role,
pays_reverse_charge, generates_eway_bills, employee_count. Loader (`ontology.load()`), house-rule
checks and the `ontology-validate` command.
