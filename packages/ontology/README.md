# ontology

The business attributes that GST rule predicates and business profiles are written against, as
one versioned YAML file with a loader and a validator. Every predicate in the rulebook and every
attribute on a business profile uses a key from this file, so the profile service and the
applicability engine read the same definitions. Core Product owns the package together with
Regulatory Intelligence; the wording of definitions and allowed values comes from the Regulatory
Analysts.

Design reference: Project Foundation guide, sections 6 and 14.

- **Owns:** `src/ontology/data/attributes.yaml` and the loader, checks and validator under `src/ontology`
- **Owning team:** Core Product, co-approved by Regulatory Intelligence
- **Consumes:** `packages/domain-kernel` (the `Ontology` model and its structural validation)
- **Emits / publishes:** ontology versions; the profile service and the applicability engine upgrade together

## What is here

- `src/ontology/data/attributes.yaml`, version 0.2.0, seventeen attributes, each with the
  hierarchy `level` it belongs to (entity or registration; ADR-016):
  - facts the GSTIN lookup pre-fills: `registration_type`, `gstin_status`, `registered_since`,
    `state_codes`, `constitution`, `business_category`
  - turnover and filing: `supply_type`, `turnover_band` (per financial year),
    `peak_turnover_band`, `return_filing_frequency`, `filing_scheme`
  - activity flags: `makes_inter_state_supplies`, `makes_zero_rated_supplies`, `ecommerce_role`,
    `pays_reverse_charge`, `generates_eway_bills`
  - size: `employee_count`
- `ontology.load()` returns the kernel's `Ontology` built from the packaged file;
  `ontology.VERSION` is the version this package ships; `ontology.data_path()` locates the file;
  `ontology.parse(text)` turns YAML text into the mapping `Ontology.from_mapping` takes.
- `uv run ontology-validate` checks the packaged file and lists its attributes. `--file path`
  checks a draft instead; a draft is not required to match `VERSION`.

The kernel owns the model and the structural validation: keys, types, sources, allowed values,
bounds, semver strings and examples. This package adds seven house rules on top: keys are
snake_case; definitions end with a period; `since` is present and not newer than `version`;
enum kinds have at least two values; values are snake_case, and state codes are exactly two
digits; a per-financial-year attribute lives at the entity level.

## How services use it

Only a composition root (the app factory or a worker's entry point) calls `ontology.load()`.
Domain and application code take the `Ontology` object as an argument and never import this
package. import-linter forbids `yaml` in every domain layer and in the kernel, and a forbidden
contract follows indirect chains, so a domain module that imports `ontology` fails the same
check.

## Adding or changing an attribute

1. Edit `attributes.yaml`. Keys are stable once released. Append new enum values rather than
   reordering; keep `ordered_enum` values in ascending order; quote codes and dates so YAML does
   not read them as numbers or dates.
2. Bump the version in three places: `version` in `attributes.yaml`, `VERSION` in
   `src/ontology/__init__.py` and `version` in `pyproject.toml`. Minor for a new attribute or
   allowed value, major for a removal or rename, patch for wording. A new attribute gets `since`
   set to the new version.
3. Update `EXPECTED_COUNT` in `tests/unit/test_load.py` when the count changes and add an entry
   to `CHANGELOG.md`.
4. Run `uv run ontology-validate` and `uv run pytest packages/ontology`.
5. Open a pull request; it needs a review from both owning teams.

## Releasing a version

The ontology version is the package version. Services pin the version they were tested against.
The profile service and the applicability engine upgrade together, because a profile saved
against one version must be evaluated against the same definitions.

## How to run

- `uv run pytest packages/ontology` from the repo root.
- `uv run ontology-validate`, or `uv run ontology-validate --file draft.yaml` for a draft.
- `make py-lint py-typecheck importlint` runs ruff, mypy (strict, tests included) and the
  import-linter contracts.
