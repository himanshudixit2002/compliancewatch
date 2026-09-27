# compliancewatch-contracts

Generated pydantic v2 models for the event contracts in `packages/contracts/events`. Do not edit
the modules under `src/cw_contracts/events`; change a schema and run `make contracts`.

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
