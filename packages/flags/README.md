# flags package

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 13 and 17 (flags default off, each with an owner and a removal condition).

- **Owns:** The feature flag registry (`registry.json`) and its JSON Schema
- **Owning team:** Platform and Infrastructure (custodian); each flag's owner decides its rollout and removal
- **Consumes:** n/a
- **Emits / publishes:** `registry.json`, read by every service through py-common's generated copy

## Layout

```
registry.json          # every rollout switch, sorted by name
registry.schema.json   # JSON Schema 2020-12 for the registry
```

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

## Adding a flag

1. Add the setting, named `*_enabled` for a bool, defaulting off.
2. Add its entry to `registry.json` in name order, with the owner, the removal condition and an
   expiry date.
3. Run `make flags` and commit `registry.json` with the regenerated copy in the same change.

Removing a flag is the reverse: delete the code path, the setting and the entry, then run
`make flags`.
