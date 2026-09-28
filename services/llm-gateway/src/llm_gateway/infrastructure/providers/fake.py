"""The deterministic provider: what local development, CI and end-to-end tests talk to.

Same request in, same text out, no network. A request with a JSON schema gets a placeholder
document that fills the schema's required fields (the first value of an enum, null when the
type allows it); the judgement feature gets an "unsure"
verdict; everything else is echoed back. ``fail_next`` injects failures so callers can test
their fallback paths.
"""

import hashlib
import json
import math
import threading
from collections.abc import Mapping

from domain_kernel._validation import require_int
from domain_kernel.llm import CompletionRequest
from llm_gateway.domain.errors import ProviderUnavailableError
from llm_gateway.domain.features import Feature
from llm_gateway.domain.providers import ProviderResponse

JUDGEMENT_TEXT = '{"confidence":0.5,"result":"unsure"}'
"""What the fake answers for the judgement feature when no schema is given."""
ECHO_TAIL = 200
"""How many trailing characters of the user text the echo repeats."""
CHARS_PER_TOKEN = 4
"""The token estimate: four characters per token, rounded up."""


class FakeProvider:
    """Serves ``fake/echo``, or whatever model id the request names, inside the process."""

    MODEL = "fake/echo"

    def __init__(self) -> None:
        self.calls = 0
        self._failures = 0
        self._lock = threading.Lock()

    def fail_next(self, count: int = 1) -> None:
        """Make the next ``count`` calls raise ``ProviderUnavailableError``."""
        with self._lock:
            self._failures = require_int(count, "count", minimum=0)

    def complete(self, req: CompletionRequest) -> ProviderResponse:
        with self._lock:
            self.calls += 1
            if self._failures > 0:
                self._failures -= 1
                raise ProviderUnavailableError("fake provider: injected failure")
        text = _text_for(req)
        return ProviderResponse(
            text=text,
            model=req.model or self.MODEL,
            input_tokens=_tokens(req.system + req.user),
            output_tokens=_tokens(text),
            provider="fake",
            cost_usd=None,
            generation_id="fake-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        )


def _tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def _text_for(req: CompletionRequest) -> str:
    if req.json_schema is not None:
        return json.dumps(_placeholder(req.json_schema), separators=(",", ":"), ensure_ascii=False)
    if req.feature == Feature.JUDGEMENT:
        return JUDGEMENT_TEXT
    return "fake:" + req.user[-ECHO_TAIL:]


def _placeholder(schema: Mapping[str, object]) -> dict[str, object]:
    """An object with every required property set to a value of its declared type."""
    required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(required, list | tuple):
        return {}
    document: dict[str, object] = {}
    for name in required:
        if not isinstance(name, str):
            continue
        prop = properties.get(name) if isinstance(properties, Mapping) else None
        document[name] = _value_for(prop)
    return document


def _value_for(prop: object) -> object:
    """A value of the property's declared type: the first value of an ``enum``, null when the
    type list allows it, otherwise the first listed type, so a schema with ``enum`` or
    ``["string", "null"]`` still gets something that fits."""
    if not isinstance(prop, Mapping):
        return None
    choices = prop.get("enum")
    if isinstance(choices, list | tuple) and choices:
        return choices[0]
    kind = prop.get("type")
    if isinstance(kind, list | tuple):
        kind = None if "null" in kind or not kind else kind[0]
    match kind:
        case "string":
            return "placeholder"
        case "number":
            return 0.0
        case "integer":
            return 0
        case "boolean":
            return False
        case "array":
            return []
        case "object":
            return {}
        case _:
            return None
