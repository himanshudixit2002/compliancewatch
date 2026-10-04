# Admin tools

The internal tools under `/admin`, for the regulatory roles (`analyst`, `reviewer`, `admin`) of
the internal tenant. Each tool is a registry entry in the `admin` section
([screens.md](screens.md) lists them with their status); a tool that is not built is served by
`admin/[...slug]` with the notice naming what it waits for. This page describes the tools that
are built: what each shows, what it calls and what waits.

The admin layout runs `requireAdmin()` before anything renders, so a tenant role gets the root
404 with no admin markup; each page calls its gate again on its first line
(`requireScreenSession`), and a regulatory role a tool's entry does not list gets the not-found
page as well ([auth-and-roles.md](auth-and-roles.md)). A page that reads a service has a sibling
`loading.tsx`; under it a not-found answer (an unknown id, a role the tool does not admit) is
streamed with status 200 and a `noindex` tag rather than a 404 status, as on the business pages
(D-029 in [decisions.md](decisions.md)).

| Tool                | Route                                    | Who                     | Calls                                                                 |
| ------------------- | ---------------------------------------- | ----------------------- | --------------------------------------------------------------------- |
| Internal tools      | `/admin`                                 | every regulatory role   | the review queues, rules and prompts (one page each), every `/health` |
| Documents           | `/admin/rulebook/documents`, `/[id]`     | every regulatory role   | `GET /v1/rulebook/documents/{document_id}`                            |
| Feature flags       | `/admin/flags`                           | every regulatory role   | none: `packages/flags/registry.json` and the web server's flag reader |
| Ontology            | `/admin/ontology`                        | every regulatory role   | `GET /v1/ontology` (profile; no tenant header, cached an hour)        |

## Internal tools: `/admin`

The counts of the review queues and registries, each in its own tile with its own error state,
every service's health probed from the web server, and the tool list from the registry grouped
like the sidebar, each tool with its status and the services it depends on (D-036).

## Documents: `/admin/rulebook/documents`

Opens one rulebook document by its id or the sha256 of its source file; the viewer shows the
source facts and every clause with an anchor, and marks a clause or a span from a link (D-037).

## Feature flags: `/admin/flags`

Every entry of the shared flag registry, [`packages/flags/registry.json`](../../packages/flags/registry.json),
read from the `@compliancewatch/flags` module built into the app (no service is called):

- the name, whether it is on or off or one of several values, the variable the code reads for it,
  and for a tenant-targeted flag its allow-list variable;
- what it does and the condition under which it is removed;
- the owner and the default (off for every bool flag; a string flag's default with its values);
- the expiry date, with a badge once it is 30 days away or less ("N days left", "Expires today")
  and once it has passed ("Expired"; `make flags-check` fails on such a flag, so it is only seen
  between the date and the fix);
- the value on the web server, for the flags the web app reads (`services` holds `web`): what
  `server/flags.ts` answers for the session's tenant, through the provider `CW_FLAGS_PROVIDER`
  names. A flag only other services read says which ones read it; their values live in their
  own processes and Unleash, which the web server cannot see, so none is guessed.

The summary counts the flags, the web flags that are on, and those near or past their expiry.
When the web server's reader cannot be configured (Unleash chosen without its address, say), the
page shows the reason as an error and no value, since every web flag would read as off. There is
no control that changes a flag: a flag moves through its variable in local and test, or through
Unleash ([feature-flags.md](feature-flags.md)).

## Ontology: `/admin/ontology`

The business attributes a profile holds, read from the profile service's `GET /v1/ontology`
through `server/ontology.ts` (no tenant header; cached an hour under `profile:ontology`, the
lifetime the service states; D-024). Nothing is restated in the web app: every question, help
line, meaning and value label is the service's.

- The facts: the attribute set's version, the wording's version and language, whether an analyst
  has reviewed the wording (`review_status`), and the number of attributes.
- One table per level of the business hierarchy that holds attributes (the legal entity, a
  registration, a location; ADR-016), in the ontology's order, which is the order onboarding asks
  in. Each attribute shows its key, its type and where its value comes from (pre-filled from the
  GSTIN lookup, asked, or worked out by the service), whether it is stated per financial year, the
  question and help line (or that it is not asked), its meaning, the allowed values with their
  labels or a number's bounds, the ontology's example worded with the labels, and the operators a
  rule predicate may use on its type.
- An attribute whose type, level or source the web app does not know is left out and named in a
  warning, so a new kind on the service shows up as a gap rather than as the wrong text.
- The page is read-only: the ontology changes with a release of `packages/ontology`.

The usage per attribute (how many profiles hold it and in which state, and the rules that read it)
is the registry entry `admin.ontology.usage`, a component of this page that waits for
`GET /v1/profile/admin/attribute-usage` (services track, WP30). The page shows a note built from
that entry naming the route (D-039 in [decisions.md](decisions.md)).
