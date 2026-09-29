# Business pages

The list of a tenant's businesses and the pages of one business: its hierarchy, its answers per
financial year, the snapshot the applicability engine evaluates, and the review tasks the
answers opened. They are the registry entries `owner.businesses`, `owner.business`,
`owner.business.profile`, `owner.business.attributes`, `owner.business.snapshot` and
`owner.business.review-tasks`, readable by every tenant member role (`owner`, `staff`,
`ca_admin`, `ca_staff`, `compliance_lead`) in a business or CA-firm tenant; changing an answer,
adding a location or adding a GSTIN needs the `profile.edit` capability, which a compliance lead
does not have.
The calls are listed in [data-layer.md](data-layer.md) under "Businesses".

## The list: `/businesses`

Where every tenant role lands after signing in. It lists the tenant's businesses by name, 20 at
a time, from `GET /v1/businesses` with the service's opaque cursor; each row gives the name, the
PAN, the registrations' GSTINs and when the business last changed.

- A business tenant with exactly one business is sent straight to it. A CA firm always sees its
  list, headed "Clients". Because the list is then out of reach, the business's home carries
  "Add another business" (the business step, for a role that onboards), and its profile page adds
  another GSTIN of the same business.
- The search box takes a name, a PAN or a GSTIN, or part of one, in any case. Identifiers do not
  belong in a URL, so the term and the cursor are posted to the `searchBusinesses` server action
  and the table is redrawn from its answer; a searched page is not bookmarkable (D-030). The
  unfiltered first page is rendered on the server.
- Empty, the list says why and links to onboarding; a search with no match says so and how to
  widen it.

## One business: `/b/[businessId]`

The business id is the id of its legal entity node, as the business API returns it. Every page
of a business shares one header (breadcrumbs with the business's name, then a row of tabs built
from the registry's business group), so the screens not built yet (Changes, Reminders) appear as
tabs that lead to their "not available yet" notices.

A business that does not exist, belongs to another tenant (the service answers 404 for it), or
whose id is not a UUID is the not-found page. The pages stream behind their `loading.tsx`, so
that page arrives with status 200 and a `noindex` robots tag, as Next documents for streamed
responses (D-029).

Nodes are named by what identifies them, with their name: the entity by its PAN, a registration
by its GSTIN, a location by its label. A registration is named after its business unless it was
given a name of its own, so the identifier is what tells nodes apart.

| Page                          | What it shows                                                                                                                                                        |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/b/[businessId]`             | The name, PAN and registrations, "Add another business", the onboarding progress from the checklist with a link back to the questions, a tile per page, and the screens not built yet |
| `/b/[businessId]/profile`     | The hierarchy: the entity, each registration, a form per registration to add a location, and a form to add another GSTIN of the business                             |
| `/b/[businessId]/attributes`  | One node and one financial year: the node's own values, the values it inherits, what is not answered yet, and changing an answer                                  |
| `/b/[businessId]/snapshot`    | One node and one financial year: every value the engine evaluates and where it comes from                                                                           |
| `/b/[businessId]/review-tasks` | Every review task on the entity and its registrations, open ones first, with the reason, the node, the year and when it was opened                                 |

## The hierarchy and locations

A business is an entity (the PAN) with registrations (GSTINs) under it; a registration may have
locations. `GET /v1/businesses/{id}` returns the entity and its registrations. Adding a location
posts `POST /v1/profile/locations` with the registration, a label (1 to 80 characters, its
natural key under the registration) and a name; the action first checks that the registration is
part of this business, so a tampered form cannot reach another business. The same label again
answers "already under this registration". The profile service has no route that lists a
registration's locations, so the page says so, and a location is reached from the links shown
when it is added (its attributes and its snapshot, by `?node=<location id>`).

## Another GSTIN of the business

The profile page's "Add a GSTIN" form adds a registration with
`POST /v1/businesses/{id}/registrations` and the Idempotency-Key the page rendered into it
(`profile.add-registration`), so a double submit adds it once; "Add another GSTIN" then loads the
page afresh, so the next form has a new key. The GSTIN must carry the business's PAN: the action
reads the business first and says so on the field when it does not (a GSTIN of another PAN is
another business, which the business step adds; the section links to it). Like creating a
business, adding a GSTIN runs the GSTIN lookup on it, so it needs the required consents on file
(`server/required-consents.ts`): without them the section points to the consent step instead of
showing the form, and `addRegistration` refuses before any profile call. The answer names the
GSTIN, whether it is new or was already a registration of the business, and what the lookup filled
in or, when no lookup answered (every GSTIN but the demo `29ABCDE1234F1Z5` on the built-in static
lookup), that a `verify_registration` review task was opened; it links to the registration's
attributes and to the review tasks, and the hierarchy above shows the new registration.

## Attributes per financial year

`/attributes` and `/snapshot` show one node and one financial year, chosen with
`?node=<id>&fy=<label>` (node ids and year labels are not personal data); the defaults are the
entity and the current Indian financial year (April to March, labelled `2026-27`). A node must be
the entity, one of its registrations, or a location under one of them; anything else is the
not-found page.

- The node's own values: the attribute's label and help from the ontology, the state (Answered,
  Not sure, Does not apply) as text, never colour alone, the value worded by the ontology (option
  labels, Yes and No, numbers in en-IN grouping, dates in IST), the year for a per-year
  attribute, where the value came from (the GSTIN lookup, a person, or worked out by the service)
  and when it changed.
- The values the node inherits from its ancestors, in a table of their own.
- The attributes of the node's level with no answer for that year, each with an "Answer" link.
- Changing an answer (`?edit=<key>`) uses the same form and the same three answers as the
  questions step and stores it with `PATCH /v1/businesses/{id}` for that node and year; the
  status line names the profile version the change made. A per-year answer belongs to its year
  only: another year asks for it again.

## The snapshot and where a value comes from

`GET /v1/profile/nodes/{id}/snapshot?fy=` returns what the applicability engine evaluates for a
node and a year: its own known values and those it inherits. The page names the origin of each
value: "Stored on this node", "Inherited from" the nearest ancestor holding a known value (the
snapshot's `lineage` lists the ancestors from the entity down, and the node itself is its
`business_id`), or worked out by the service for a derived attribute. A child's value wins over
an ancestor's.

## Review tasks

The tasks on the entity and each registration (`GET /v1/profile/nodes/{id}/review-tasks`),
each with its reason in words:

| Reason                   | Shown as                                          | Opened when                                                        |
| ------------------------ | ------------------------------------------------- | ------------------------------------------------------------------ |
| `not_applicable`         | You said this does not apply; an analyst will confirm | An answer was Does not apply                                   |
| `confirm_financial_year` | Confirm this value for the new financial year     | The year's confirmation run (`profile-fy-confirm`, or `POST /v1/profile/financial-year-confirmations`) found a per-year value not stated for that year |
| `verify_registration`    | GSTIN details not verified by a lookup provider   | No GSTIN lookup answered when the registration was added          |

The page is read-only: resolving a task waits for a profile route nobody has designed yet
(the registry entry names it as unplanned).

## What waits

- Listing a registration's locations: a children route on the profile service.
- The changes and reminders of a business: their tabs lead to "not available yet" notices that
  name the routes they wait for. The obligation list, the calendar and ask arrive with the
  obligation and qa routes, and the obligation dashboard on the home page with them.
- Resolving a review task from these pages: an unplanned profile route.
