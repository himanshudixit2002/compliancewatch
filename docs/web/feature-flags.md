# Feature flags

The web app's flags are declared in the repository's flag registry,
[`packages/flags/registry.json`](../../packages/flags/registry.json), next to every other
rollout switch; [packages/flags/README.md](../../packages/flags/README.md) describes the entry
format, the check and the two SDKs. `apps/web/src/shared/config/flags.ts` keeps only the typed
list of the web flag names. Nothing on `main` reads a web flag yet: there is no server-side
reader, no page or action is gated, and the navigation hides a flagged registry entry because no
reader says otherwise. A flag therefore changes nothing today; the entries exist so the screen
registry can name the flag a screen will be gated by, and so the reader, when it arrives, reads
declared flags only.

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
| `web.publish_actions`       | regulatory-intelligence | The publish workflow actions on a rule version                                |
| `web.qa_enabled`            | ai-platform             | The ask screen                                                                |
| `web.tenant_header_off`     | identity-partner        | Stops sending `x-tenant-id` once services take the tenant from a token        |

None of the six is read anywhere on `main`.

## Rules for the reader, when it exists

These are the rules the entries are built for, so a reader that arrives later has nothing to
renegotiate: it reads through `@compliancewatch/flags/server` (`isEnabled(name, { tenantId })`),
on the server only, and a flag never reaches the browser; the `CW_WEB_FLAG_<NAME>=true` override
is honoured only when `CW_WEB_ENV` is `local` or `test`; a gated form renders a `Banner` naming
the flag, and a gated action refuses with a message naming the flag, rather than either
disappearing silently.
