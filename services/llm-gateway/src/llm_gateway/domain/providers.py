"""What a provider adapter returns: the kernel response plus what the ledger wants."""

from dataclasses import dataclass
from decimal import Decimal

from domain_kernel._validation import require_instance
from domain_kernel.errors import InvariantViolationError
from domain_kernel.llm import CompletionResponse


@dataclass(frozen=True, slots=True)
class ProviderResponse(CompletionResponse):
    """A completion with the host that served it and the cost the gateway reported.

    ``cost_usd`` is None when the provider gave no figure and the price table estimates it.
    """

    provider: str = ""
    cost_usd: Decimal | None = None
    generation_id: str = ""

    def __post_init__(self) -> None:
        CompletionResponse.__post_init__(self)
        require_instance(self.provider, str, "provider")
        if self.cost_usd is not None and (
            not isinstance(self.cost_usd, Decimal) or not self.cost_usd.is_finite()
        ):
            raise InvariantViolationError(f"cost_usd must be a Decimal, got {self.cost_usd!r}")
        require_instance(self.generation_id, str, "generation_id")
