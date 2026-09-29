# compliancewatch-contracts

Generated pydantic v2 models for the contracts in `packages/contracts`: the events
(`cw_contracts.events`, from `packages/contracts/events`) and the public REST API
(`cw_contracts.rest.public_v1`, from `packages/contracts/openapi/public.v1.json`). Do not edit
the generated modules; change a schema and run `make contracts`, or for the public API change
the service and run `make openapi SERVICE=<name>` and `make openapi-public`.

```python
from cw_contracts.events import TOPICS, EventEnvelopeV1
from py_common.events import decode

message = decode(raw_bytes)  # the envelope
spec = TOPICS[message.topic]  # version, model, tenant scoping
payload = spec.model.model_validate(message.payload)
```

Models ignore unknown fields (tolerant reader) and reject missing required ones, wrong enum
values and naive datetimes. The tests under `tests/unit` check every golden example against the
schemas and the models, the CHANGELOG lines, and the `check_compat.py` script.

```python
from cw_contracts.rest import public_v1 as api

body = api.BusinessIn(name="Acme", gstin=api.Gstin("29ABCDE1234F1Z5"))
response = client.post(
    "/v1/businesses",
    json=body.model_dump(mode="json", exclude_none=True),
    headers={"Idempotency-Key": key, "x-tenant-id": tenant},
)
created = api.BusinessCreatedOut.model_validate(response.json())
```

The REST module has one model per schema of the spec, and its docstring names the spec version
it was generated from. Response models ignore unknown fields; request models refuse them, as
the services do. `tests/unit/test_rest_client.py` checks that every schema has its model with
the same fields and required fields, and `tests/unit/test_public_openapi.py` checks the public
spec and its builder.
