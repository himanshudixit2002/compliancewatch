# Changelog

Versions follow semver. A new attribute or allowed value is a minor bump, a removed or renamed
one is a major bump, wording is a patch.

## Unreleased

Draft English wording, version 0.1.0 of `data/wording.en.yaml` (review status needs_review): a
question for each of the seventeen attributes and a label for every allowed value, loaded and
checked against the attribute set by `ontology.load_wording()` (`WORDING_VERSION`). The
attribute set stays at 0.2.0.

## 0.2.0 - 2026-09-28

Every attribute declares its `level` in the business hierarchy (ADR-016): `state_codes`,
`constitution`, `business_category`, `turnover_band`, `peak_turnover_band` and
`employee_count` at the entity (PAN); every other attribute at the registration (GSTIN).
`turnover_band` is `per_financial_year`: a profile stores it with the year it is as of.
New attribute `filing_scheme` (regular_monthly, regular_qrmp, composition), the scheme a
registration files under. House rules: `since` is required, and a per-financial-year attribute
lives at the entity level.

## 0.1.0 - 2026-09-27

First release. Sixteen GST attributes: registration_type, gstin_status, registered_since,
state_codes, constitution, business_category, supply_type, turnover_band, peak_turnover_band,
return_filing_frequency, makes_inter_state_supplies, makes_zero_rated_supplies, ecommerce_role,
pays_reverse_charge, generates_eway_bills, employee_count. Loader (`ontology.load()`), house-rule
checks and the `ontology-validate` command.
