# contracts package

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, sections 7 (event contract rules), 10, 13 and 14.

- **Owns:** OpenAPI specs, event schemas (JSON Schema), generated clients (py + ts), and the event changelog
- **Owning team:** Platform and Infrastructure (custodian); every consuming team reviews a contract change
- **Consumes:** n/a
- **Emits / publishes:** Versioned contracts (semver); services pin the versions they consume

## Layout

```
openapi/             # OpenAPI 3.1 specs, public /v1 and internal service APIs
  llm-gateway.v1.json   # the first one: services/llm-gateway
events/              # JSON Schema per event topic (object.verb, past tense) with changelog entries
clients/python/      # generated Python clients
clients/typescript/  # generated TypeScript clients
```

## OpenAPI specs

A spec is generated from the running service, committed here, and reviewed like code: the diff in
the pull request is the contract change. `services/llm-gateway/tests/contract/test_openapi.py`
fails when the served schema and the committed file differ, so an API change without a spec
change cannot pass `make test`.

```bash
make openapi SERVICE=llm-gateway   # writes openapi/llm-gateway.v1.json (indent 2, sorted keys)
```

The files are generated JSON: prettier ignores `openapi/` and nobody edits them by hand. Every
service shares one error shape, `Problem` (RFC 9457 problem details from py-common), published
under `components.schemas` and referenced by each route's error responses. The description of
each problem response is the interpreter's `http.HTTPStatus` phrase, so a Python minor bump that
rewords a phrase may require regenerating the specs.

## Events and clients

No event schema is committed yet; the first topics (`llm.call.completed`, `llm.budget.alarmed`)
are logged by the gateway and get a schema here when the Kafka outbox lands. No client is
generated yet: `package.json` only makes the workspace resolve, and the Python client side joins
the uv workspace when the first client is generated.
