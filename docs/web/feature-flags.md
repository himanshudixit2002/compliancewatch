# Feature flags

The web app's flags are declared in the repository's flag registry,
[`packages/flags/registry.json`](../../packages/flags/registry.json), next to every other
rollout switch; [packages/flags/README.md](../../packages/flags/README.md) describes the entry
format, the check and the two SDKs. `apps/web/src/shared/config/flags.ts` keeps only the typed
list of the web flag names, and `apps/web/src/server/flags.ts` is the reader. Three flags are
read on `main`: `web.analytics_enabled`, by the product events (`server/analytics.ts`), and
`web.admin_rulebook_writes` and `web.publish_actions`, by `server/api/rulebook-write.ts` before it
sends an analyst's decision, or a rule version's citations or workflow step, to the rulebook. The
navigation still hides a flagged registry entry, because no flagged screen is built yet.

## An entry

```json
{
  "name": "web.qa_enabled",
  "type": "bool",
  "default": false,
  "owner": "ai-platform",
  "description": "The web app's ask screen on the qa ask route.",
  "removal": "When the qa ask route is on for every tenant.",
  "expires": "2027-03-31",
  "targeting": "none",
  "env": "CW_WEB_FLAG_QA_ENABLED",
  "services": ["web"]
}
```

- `name`: `web.` followed by a snake_case name.
- `type` and `default`: a bool that is `false`. A flag is off until someone turns it on,
  everywhere.
- `owner`: one of `core-product`, `platform`, `regulatory-intelligence`, `ai-platform`,
  `identity-partner`.
- `removal` and `expires`: the condition under which the flag goes away, in plain words, and the
  date by which it is removed or its owner extends it. A switch without a removal condition is a
  setting, and a setting is configuration (`CW_WEB_ENV` and the auth provider choice are
  configuration, not flags).
- `env`: the override variable, `CW_WEB_FLAG_<NAME>` (the name after `web.`, upper-cased), which
  `envVarFor(name)` derives. The reader honours it only when `CW_WEB_ENV` is `local` or `test`.
- `services`: `["web"]`, the app's directory name.

`make flags-check` (in `make check` and the CI Python job) validates every entry against the
registry's schema and rules. `flags.test.ts` in the app fails when `FLAG_NAMES` and the
registry's `web.*` entries differ, when a web entry is not an off bool read by `web`, or when its
`env` is not `envVarFor(name)`. `FlagName` is the union of the names, which is what the screen
registry's `flag` field and the navigation's `isFlagEnabled` callback are typed with.

Adding a web flag: add its entry to `registry.json` in name order, run `make flags` (it rewrites
py-common's generated copy of the registry), add the name to `FLAG_NAMES`, and commit the three
files together.

## Declared today

| Name                        | Owner                   | What it will gate                                                             |
| --------------------------- | ----------------------- | ----------------------------------------------------------------------------- |
| `web.admin_rulebook_writes` | regulatory-intelligence | Entity and relation decisions from `/admin` through a server-side write token |
| `web.analytics_enabled`     | core-product            | Product events for sessions that granted the analytics consent                |
| `web.otel_enabled`          | platform                | OpenTelemetry registration in `instrumentation.ts`                            |
| `web.publish_actions`       | regulatory-intelligence | Citations and the publish workflow on a rule version's page                   |
| `web.qa_enabled`            | ai-platform             | The ask screen                                                                |
| `web.tenant_header_off`     | identity-partner        | Stops sending `x-tenant-id` once services take the tenant from a token        |

`web.analytics_enabled` is read by `server/analytics.ts`, and `web.admin_rulebook_writes` and
`web.publish_actions` by `server/api/rulebook-write.ts`; the other three are not read yet. The e2e
run turns `web.publish_actions` on through its override (the Playwright config), so the rule
version specs can cite, submit, approve and return drafts.

## The reader

`server/flags.ts` exports `isEnabled(name, { tenantId })`, typed with `FlagName`, for pages,
actions and server modules. It answers through `@compliancewatch/flags/server`, which it
configures once per server process on the first question, with the provider `CW_FLAGS_PROVIDER`
names (`env` by default, or `unleash`; see the package README):

- The env provider reads the entry's `env` variable, `CW_WEB_FLAG_<NAME>`, then the SDK's generic
  `CW_FLAG_WEB_<NAME>`. The reader passes those variables (and their `__TENANTS` lists) through
  only when `CW_WEB_ENV` is `local` or `test`; in `staging` and `prod` it removes them from what
  the provider sees, so a stray variable cannot switch a flag on there, and a flag is turned on
  through Unleash.
- A provider that cannot be configured (`unleash` without `CW_UNLEASH_URL`, say) answers off for
  every flag, logs one `flag_configuration_failed` JSON line, and is tried again on the next
  question.
- A flag is read on the server only and never reaches the browser.

A gated form renders a `Banner` naming the flag, and a gated action refuses with a message
naming the flag, rather than either disappearing silently. `flags.test.ts` in `server/` covers
the default, the override in local and in prod, and the failed configuration.

`flagProviderStatus()` says which provider the reader answers through (`env` or `unleash`), or
why it could not be configured. The flag console uses it.

## The flag console

`/admin/flags` (every regulatory role) lists every entry of the registry, not only the web
flags: the name, the variable, the description and removal condition, the owner, the default,
the expiry date with a badge once it is 30 days away or past, and, for the flags the web app
reads, the value `isEnabled` answers for the session's tenant. A flag only other services read
says which ones read it instead of a value, because the web server cannot see their variables.
When the reader cannot be configured the page shows why and evaluates nothing. Nothing on the
page changes a flag. [admin-tools.md](admin-tools.md) has the detail.

## Product analytics

`server/analytics.ts` exports `track(principal, event)`. An event is one JSON line on stdout
(`"event": "product_event"`, the name, the time, the tenant and user ids, the properties) and an
event named `product.<name>` on the active OpenTelemetry span, which records only once tracing is
registered. It is emitted only when both hold, checked in this order on every call:

1. `web.analytics_enabled` is on for the tenant. With it off (the default) nothing else happens:
   no read, no line.
2. The person's analytics consent is current: the latest `analytics` record from
   `GET /v1/identity/consents?subject=<user id>`, read on every event, grants it with the privacy
   notice's version this build ships (`privacy-notice@<Version line>`). A withdrawal stops the
   next event, and a new privacy notice stops them until the person agrees again. The session's
   `analyticsConsent` claim is not read, because nothing refreshes it when a person withdraws.

The events are a closed union in the module; a property is a count, a boolean, or a value from
a fixed list, never text a person typed, an answer's value, a GSTIN, a phone number or an
address:

| Event                           | Emitted by                                          | Properties                                                |
| ------------------------------- | --------------------------------------------------- | --------------------------------------------------------- |
| `onboarding_step_completed`     | the consent step, the business step, each answer    | `step`; `created` and `looked_up`; `attribute` and `state` |
| `onboarding_summary_viewed`     | each view of the onboarding summary                 | `complete`, `answered`, `total`, `unsure`, `open_review_tasks` |
| `consent_changed`               | a recorded change on the consents page              | `purpose`, `change`                                       |
| `notification_preference_saved` | a saved preference                                  | `channel`, `opted_in`                                     |
| `subscription_started`          | a started subscription                              | `plan_key`                                                |

`track` never throws and never fails the request it runs in: a failure is logged as one
`product_event_failed` warning and the event is dropped. Nothing is sent to a third party.
Turning the flag on anywhere waits for counsel's view on the analytics consent purpose.
