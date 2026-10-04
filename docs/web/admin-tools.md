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
