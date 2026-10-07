# flags package

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 13 and 17 (flags default off, each with an owner and a removal condition).

- **Owns:** The feature flag registry (`registry.json`), its JSON Schema, and the OpenFeature client for TypeScript servers
- **Owning team:** Platform and Infrastructure (custodian); each flag's owner decides its rollout and removal
- **Consumes:** n/a
- **Emits / publishes:** `registry.json`, read by every Python service through py-common's generated copy and by TypeScript through `@compliancewatch/flags`

## Layout

```
registry.json          # every rollout switch, sorted by name
registry.schema.json   # JSON Schema 2020-12 for the registry
src/index.ts           # @compliancewatch/flags: FlagDefinition, REGISTRY, UnknownFlagError; no Node API
src/server.ts          # @compliancewatch/flags/server: configureFlags, isEnabled, flagValue (OpenFeature)
src/server.test.ts     # vitest: the env provider, tenant targeting, the Unleash provider over a fake client
```

The package is consumed from source through `exports`, like `@compliancewatch/ui`; its relative
imports carry the `.ts` extension, so Node runs it directly.

`packages/py-common/src/py_common/flags_registry.json` is generated from `registry.json` by
`make flags`; never edit it by hand.

## An entry

| Field         | Meaning                                                                                          |
| ------------- | ------------------------------------------------------------------------------------------------ |
| `name`        | Dotted and lower case, `<area>.<switch>`, such as `qa.kag` or `profile.gstin_category_prefill`  |
| `type`        | `bool`, or `string` for a switch between providers or modes                                      |
| `default`     | `false` for a bool flag; for a string flag the value that keeps the new behaviour off           |
| `values`      | A string flag's values; its default is one of them                                               |
| `owner`       | `core-product`, `platform`, `regulatory-intelligence`, `ai-platform` or `identity-partner`       |
| `description` | What turning it on does                                                                          |
| `removal`     | The condition under which the flag is deleted from the code and from the registry               |
| `expires`     | The date by which the flag is removed, or its owner extends the date with a reason              |
| `targeting`   | `tenant` when the flag can be on for some tenants only, otherwise `none`                         |
| `env`         | The environment variable the code already reads for the switch, when it has one                 |
| `tenants_env` | The variable holding the tenant allow-list, when the code already reads one (`CW_QA_KAG_TENANTS`) |
| `services`    | The services, apps and packages that read the flag, by directory name                            |

## The check

`make flags-check` runs in `make check` and in the CI Python job. It validates the registry
against the schema, then requires unique names in sorted order, each environment variable read by
one flag only, a false default for every bool flag, a string flag's default among its values,
services that exist, and an `expires` date that has not passed. An expired flag fails the check
until it is removed or its owner moves the date. It also fails when py-common's copy differs from
the registry.

It then reads every settings module (`packages/py-common/src/py_common/settings.py`,
`services/*/src/*/settings.py` and `composition/*/src/*/settings.py`) and classifies each bool
and `Literal` field:

- A field is a flag when it is a bool named `*_enabled`, when its name ends in `_provider`,
  `_mode` or `_backend`, or when it is listed in `SWITCH_FIELDS` in `infra/scripts/check_flags.py`
  (such as `profile_gstin_lookup`). A flag needs an entry whose `env` is the field's `CW_*`
  variable, with the same type, default and values.
- Every other bool or `Literal` field is configuration, such as a store selector, the log level or
  `CW_LLM_EMBEDDING_DIMENSIONS_PARAM`, and is listed in `NOT_FLAGS` with the reason.
- A field named `*_tenants` is a flag's tenant allow-list and is the `tenants_env` of its entry.

A field that is neither fails the check, so a new switch cannot ship unregistered. Entries without
a settings field are allowed: the WhatsApp bot's switches are read in TypeScript.

## Reading a flag

Python services use `py_common.flags` (packages/py-common/README.md, "Feature flags"): call
`configure_flags(settings)` at start-up, then `flag_enabled(name, tenant_id)` or
`flag_value(name)`. TypeScript servers use `@compliancewatch/flags/server` the same way:
`await configureFlags(process.env, { serviceName })` at start-up, then
`await isEnabled(name, { tenantId })` or `await flagValue(name)`; `unleash-client` is loaded only
when Unleash is chosen. Both answer the same way. `CW_FLAGS_PROVIDER` picks the provider:

- `env` (the default) reads the entry's `env` variable, else `CW_FLAG_<NAME>` (the name upper
  cased, dots as underscores), else the default. A tenant-targeted flag that is on narrows to its
  allow-list, `tenants_env` or `CW_FLAG_<NAME>__TENANTS`; with no list it is on for every tenant.
- `unleash` reads an Unleash server at `CW_UNLEASH_URL` with the client token
  `CW_UNLEASH_API_TOKEN`. Create each flag the code reads through these clients in Unleash under
  its registry name; a string flag is a variant whose payload (or name) is one of its values. The
  tenant id is Unleash's `userId`. `make dev-flags` starts one locally.

A flag Unleash does not hold, or a value that does not parse, answers the default and is
logged as `flag_evaluation_failed`. A name the registry does not hold throws (`UnknownFlagError`
in both languages).

Only a flag the code reads through `py_common.flags` or `@compliancewatch/flags` follows
`CW_FLAGS_PROVIDER`, and today that is `profile.gstin_category_prefill` and
`web.analytics_enabled` (the web app's other `web.*` flags are not read yet). Every other entry
(`rulebook.publish`, `qa.kag`, `notification.whatsapp`, `pipeline.knowledge`,
`identity.billing_provider`, `llm_gateway.provider`, `llm_gateway.residency`,
`profile.gstin_lookup`, `flags.provider` and the WhatsApp bot's two switches) is a setting or an
environment variable that its service reads once at start-up. Those entries are registered for
their owner, default, removal condition and expiry date only: turning one on in Unleash changes
nothing. Set its `env` variable and restart the service instead. An entry moves to the provider
when its code starts reading it through one of the two clients.

`llm_gateway.residency` never moves there: the residency policy is a decision taken with counsel
(ADR-020), not a rollout, so the gateway reads `CW_LLM_RESIDENCY` alone. Its entry is that
setting's record, and the gateway refuses to start with `CW_FLAG_LLM_GATEWAY_RESIDENCY` set or
with `CW_LLM_RESIDENCY` empty, so the env provider answers the policy the gateway runs. Nothing
reads the flag, from either provider; do not create it in Unleash.

## Adding a flag

1. Add the setting, named `*_enabled` for a bool, defaulting off; or, for a flag the code reads
   through `flag_enabled`, no setting at all.
2. Add its entry to `registry.json` in name order, with the owner, the removal condition and an
   expiry date.
3. Run `make flags` and commit `registry.json` with the regenerated copy in the same change.

Removing a flag is the reverse: delete the code path, the setting and the entry, then run
`make flags`.

## How to run

`make flags-check` (the registry), `pnpm --filter @compliancewatch/flags test` (vitest, 80%
coverage thresholds), `lint` and `typecheck`. The Unleash provider's integration test against a
real server is in py-common (`packages/py-common/tests/integration/test_unleash_provider.py`).
