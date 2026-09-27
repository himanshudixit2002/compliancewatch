"""Request and response shapes for the model gateway."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from domain_kernel._validation import (
    freeze_mapping,
    require_bool,
    require_finite,
    require_instance,
    require_int,
    require_text,
)
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    """One completion call. ``feature`` and ``prompt_version`` name the prompt in the ledger.

    ``metadata`` carries caller tags for the trace (a document id, a workflow run): string keys
    and string values only, never prompt content.
    """

    feature: str
    prompt_version: str
    system: str
    user: str
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int = 1024
    json_schema: Mapping[str, object] | None = field(default=None, hash=False)
    tenant_id: TenantId | None = None
    metadata: Mapping[str, str] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        require_text(self.feature, "feature")
        require_text(self.prompt_version, "prompt_version")
        require_instance(self.system, str, "system")
        require_text(self.user, "user", strip=False)
        if self.model is not None:
            require_text(self.model, "model")
        temperature = require_finite(self.temperature, "temperature")
        if not 0 <= temperature <= 2:
            raise InvariantViolationError(f"temperature must be within [0, 2], got {temperature}")
        require_int(self.max_tokens, "max_tokens", minimum=1)
        if self.json_schema is not None:
            object.__setattr__(self, "json_schema", freeze_mapping(self.json_schema, "json_schema"))
        if self.tenant_id is not None:
            require_instance(self.tenant_id, TenantId, "tenant_id")
        tags: dict[str, str] = {}
        for key, value in freeze_mapping(self.metadata, "metadata").items():
            if not isinstance(value, str):
                raise InvariantViolationError(
                    f"metadata values must be strings, got {value.__class__.__name__} for {key!r}"
                )
            tags[key] = value
        object.__setattr__(self, "metadata", MappingProxyType(tags))


@dataclass(frozen=True, slots=True)
class CompletionResponse:
    """What came back, with the token counts the cost ledger records."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cached: bool = False
    trace_id: str = ""

    def __post_init__(self) -> None:
        require_instance(self.text, str, "text")
        require_text(self.model, "model")
        require_int(self.input_tokens, "input_tokens", minimum=0)
        require_int(self.output_tokens, "output_tokens", minimum=0)
        require_bool(self.cached, "cached")
        require_instance(self.trace_id, str, "trace_id")
