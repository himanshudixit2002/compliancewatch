# Feature flags

The web app declares its flags as data in `apps/web/src/shared/config/flags.ts`. This page
describes the declaration and the rules the test enforces. Nothing on `main` reads a flag yet:
there is no server-side reader, no page or action is gated, and the navigation hides a flagged
registry entry because no reader says otherwise. A flag therefore changes nothing today; the
declarations exist so the registry can name the flag a screen will be gated by and so the
reader, when it arrives, has a typed list to read.

## Declaration

```ts
{
  name: "web.qa_enabled",
  owner: "ai-platform",
  default: false,
  removal: "When the qa ask route is on for every tenant.",
  description: "The ask screen on the qa ask route.",
}
```

- `name`: `web.` followed by a snake_case name. The environment prefix is not part of the
  name; `envVarFor(name)` derives the override variable (`web.qa_enabled` becomes
  `CW_WEB_FLAG_QA_ENABLED`).
- `owner`: one of `core-product`, `platform`, `regulatory-intelligence`, `ai-platform`,
  `identity-partner`.
- `default`: always `false`. A flag is off until someone turns it on, everywhere.
- `removal`: the condition under which the flag goes away, in plain words. A flag without a
  removal condition is a setting, and a setting is configuration (`CW_WEB_ENV` and the auth
  provider choice are configuration, not flags).
- `description`: what turns on.

`flags.test.ts` fails on a default other than `false`, a missing owner, a removal or
description shorter than a sentence, a name outside the pattern, or a duplicate. `FlagName` is
the union of the declared names, which is what the registry's `flag` field and the navigation's
`isFlagEnabled` callback are typed with.

## Declared today

| Name                        | Owner                   | What it will gate                                                            |
| --------------------------- | ----------------------- | ---------------------------------------------------------------------------- |
| `web.analytics_enabled`     | core-product            | Product events for sessions that granted the analytics consent               |
| `web.otel_enabled`          | platform                | OpenTelemetry registration in `instrumentation.ts`                           |
| `web.admin_rulebook_writes` | regulatory-intelligence | Entity and relation decisions from `/admin` through a server-side write token |
| `web.qa_enabled`            | ai-platform             | The ask screen                                                               |
| `web.publish_actions`       | regulatory-intelligence | The publish workflow actions on a rule version                               |
| `web.tenant_header_off`     | identity-partner        | Stops sending `x-tenant-id` once services take the tenant from a token       |

None of the six is read anywhere on `main`.

## Rules for the reader, when it exists

These are the rules the declaration shape is built for, so a reader that arrives later has
nothing to renegotiate: a flag is read on the server only and never reaches the browser; the
`CW_WEB_FLAG_<NAME>=true` override is honoured only when `CW_WEB_ENV` is `local` or `test`; a
gated form renders a `Banner` naming the flag, and a gated action refuses with a message naming
the flag, rather than either disappearing silently. When the repository gains a shared flag
registry package, these declarations move there and `flags.ts` keeps the typed name list.
