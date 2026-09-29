# Public API changelog

The public API is `public.v1.json`, which `make openapi-public` builds from the operations the
services tag `public`. Its version is `info.version` in `public.meta.json` and follows semver:
a new operation, or a new optional field or parameter, is a minor bump; a fix to wording or
documentation is a patch; a break (see `BREAKING.md`) is a major bump and a new `public.v2.json`
next to this one. The change that bumps the version adds its section here, and the build fails
while the version in `public.meta.json` has no section.

## 0.1.0

First version, from the profile service:

- `POST /v1/businesses` creates a business from its GSTIN, or from its PAN alone, and answers
  the GSTIN pre-fill and the first onboarding question. It requires an `Idempotency-Key`
  header and answers 428 without one.
- `GET /v1/businesses` lists the tenant's businesses by name, a page at a time, with a search
  over name, PAN and GSTIN.
- `GET /v1/businesses/{business_id}` and `PATCH /v1/businesses/{business_id}` read and update
  one business, all changes or none.
- `GET /v1/businesses/{business_id}/onboarding` answers the next onboarding question with its
  wording and labelled options, and how many are answered.
- `POST /v1/businesses/{business_id}/registrations` adds a GSTIN registration to a business. It
  requires an `Idempotency-Key` header and answers 428 without one.
- `GET /v1/ontology` answers the profile attributes with their questions, value labels and the
  rule operators per type, with an ETag.
