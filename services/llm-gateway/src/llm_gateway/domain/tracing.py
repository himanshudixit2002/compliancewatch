"""What a tracer receives per call: the ledger row plus the text and parameters around it."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from domain_kernel._validation import (
    freeze_mapping,
    require_bool,
    require_finite,
    require_instance,
    require_int,
)
from domain_kernel.errors import InvariantViolationError
from llm_gateway.domain.features import CallKind
from llm_gateway.domain.ledger import LedgerEntry


@dataclass(frozen=True, slots=True)
class CallRecord:
    """One call as a trace sees it. ``system`` and ``user`` are the scrubbed texts.

    An embedding call has no system text, its scrubbed inputs as ``user``, a summary of the
    vectors as ``output`` and no ``max_tokens``.
    """

    entry: LedgerEntry
    system: str
    user: str
    output: str
    pii_counts: Mapping[str, int] = field(hash=False)
    temperature: float
    max_tokens: int | None
    has_schema: bool
    metadata: Mapping[str, str] = field(hash=False)
    error_detail: str = ""
    kind: CallKind = CallKind.COMPLETION

    def __post_init__(self) -> None:
        require_instance(self.entry, LedgerEntry, "entry")
        require_instance(self.system, str, "system")
        require_instance(self.user, str, "user")
        require_instance(self.output, str, "output")
        counts = freeze_mapping(self.pii_counts, "pii_counts")
        for kind, count in counts.items():
            require_int(count, f"pii_counts[{kind!r}]", minimum=0)
        object.__setattr__(self, "pii_counts", counts)
        require_finite(self.temperature, "temperature")
        if self.max_tokens is not None:
            require_int(self.max_tokens, "max_tokens", minimum=1)
        require_bool(self.has_schema, "has_schema")
        tags: dict[str, str] = {}
        for key, value in freeze_mapping(self.metadata, "metadata").items():
            if not isinstance(value, str):
                raise InvariantViolationError(f"metadata values must be strings, got {value!r}")
            tags[key] = value
        object.__setattr__(self, "metadata", MappingProxyType(tags))
        require_instance(self.error_detail, str, "error_detail")
        require_instance(self.kind, CallKind, "kind")


class Tracer(Protocol):
    """Receives every call; ``flush`` sends what is buffered (called at shutdown)."""

    def record(self, call: CallRecord) -> None: ...

    def flush(self) -> None: ...
