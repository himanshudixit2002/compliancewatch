# Admin tools

The internal tools under `/admin`, for the regulatory roles (`analyst`, `reviewer`, `admin`) of
the internal tenant. Each tool is a registry entry in the `admin` section
([screens.md](screens.md) lists them with their status); a tool that is not built is served by
`admin/[...slug]` with the notice naming what it waits for. This page describes the tools that
are built: what each shows, what it calls and what waits.

The admin layout runs `requireAdmin()` before anything renders, so a tenant role gets the root
404 with no admin markup; each page calls its gate again on its first line
(`requireScreenSession`), and a regulatory role a tool's entry does not list gets the not-found
page as well ([auth-and-roles.md](auth-and-roles.md)). The flags, ontology, notification and
template pages each have a sibling `loading.tsx` with a skeleton (the console's sits in the route
group `(console)`, so it wraps the console alone, as the home's sits in `(home)`); under one, a
not-found answer (an unknown id, a regulatory role the tool does not list) is streamed with status
200 and a `noindex` tag rather than a 404 status, as on the business pages (D-029 in
[decisions.md](decisions.md)). A tenant role still gets the real 404 from the layout's gate. The
document tool has no loading boundary, so its unknown ids stay real 404s (D-037).

| Tool                | Route                                    | Who                     | Calls                                                                 |
| ------------------- | ---------------------------------------- | ----------------------- | --------------------------------------------------------------------- |
| Internal tools      | `/admin`                                 | every regulatory role   | the review queues, rules and prompts (one page each), every `/health` |
| Documents           | `/admin/rulebook/documents`, `/[id]`     | every regulatory role   | `GET /v1/rulebook/documents/{document_id}`                            |
| Feature flags       | `/admin/flags`                           | every regulatory role   | none: `packages/flags/registry.json` and the web server's flag reader |
| Ontology            | `/admin/ontology`                        | every regulatory role   | `GET /v1/ontology` (profile; no tenant header, cached an hour)        |
| Notifications       | `/admin/notifications`, `/[id]`          | `analyst`, `admin`      | `GET /v1/notification/notifications`, `.../{notification_id}`, for the tenant looked up |
| Message templates   | `/admin/notifications/templates`         | every regulatory role   | `GET /v1/notification/templates` (cached five minutes)                |

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

## Notifications: `/admin/notifications`

The notification console, read-only, for the analyst and the admin. The notification routes are
tenant-scoped: a request names one tenant in `x-tenant-id` and sees that tenant's notifications
only, of one business at a time (the list needs `business_id`). The console is therefore a lookup,
as the profile review-task lookup is designed:

- A GET form takes the tenant id and the business id (ids, not personal data, so they sit in the
  query string and a lookup can be shared or bookmarked); a value that is not a UUID is marked on
  its field and nothing is read. The gateway is built with that tenant as `ClientContext.tenantId`,
  the one way a request acts for a tenant other than the session's ([data-layer.md](data-layer.md)).
- The history is the reminders pages' (D-040): newest first, 25 to a page with the service's
  cursor, filtered by delivery state with a GET form that keeps the lookup, each row named by its
  template with the occasion, channel, masked address, state, attempts and times. The service
  answers an empty page for a business id it holds nothing about, so the empty state says to check
  both ids. A failed read shows the problem and its correlation id under the form.
- `/admin/notifications/[notificationId]?tenant=<id>` is one notification: the record with the
  channel's last error, every time it moved and the values it was filled with, plus the ids an
  operator traces a delivery by (business, obligation, recipient, dispatch, the provider's message
  id). Opened without its tenant, the page asks for it with a GET form back to the same
  notification; an unknown id for that tenant is the not-found page.

Resending a notification that failed for good is not offered. The route on `main`
(`POST /v1/notification/notifications/{id}/resend`) takes no reason, checks no admin role and
needs no Idempotency-Key; the services track hardens it (WP30: a reason, the admin role, an
Idempotency-Key, an audit row). The registry keeps the action as its own entry,
`admin.notification.resend`, a capability of the notification page for the admin role, waiting
on the route with the `Idempotency-Key` header it must require (D-041), and the page shows an
admin what it waits for, from that entry.

## Message templates: `/admin/notifications/templates`

Every message template the notification service holds (`GET /v1/notification/templates`, the same
for every tenant, cached five minutes under `notification:templates`), by message, channel and
language: the name it carries at Meta, its approval status there (every template is a draft until
it is submitted from the Meta business account), its placeholders and its text. The text holds
placeholders only; the facts a message carries come from the rulebook and the obligation when it
is sent. The page sits under the console's route, so it is built with it: a static route beside
`/admin/notifications/[notificationId]` keeps `templates` from being read as a notification id.

## What waits

- The usage counts per attribute on the ontology browser: `GET /v1/profile/admin/attribute-usage`
  (services track, WP30), the waiting component `admin.ontology.usage`.
- Resending a failed notification: the hardened resend route (services track, WP30), the waiting
  capability `admin.notification.resend`.
- Reading another tenant once the services take the tenant from a bearer token: the console sends
  the looked-up tenant in `x-tenant-id`, which the notification service honours without a token
  today; with tokens it needs the admin reads the services track adds (WP30).
