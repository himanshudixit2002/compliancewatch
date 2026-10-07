"""What the composition root wires and the API reads back from ``app.state.gateway``.

Typed by domain protocols and application classes only, so the API layer never sees an adapter.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from domain_kernel.protocols import LLMProvider
from llm_gateway.application.complete import Complete
from llm_gateway.application.embed import Embed
from llm_gateway.application.usage import Usage
from llm_gateway.domain.embeddings import EmbeddingProvider
from llm_gateway.domain.ledger import CostLedger
from llm_gateway.domain.prompts import PromptRegistry
from llm_gateway.domain.residency import ResidencyPolicy
from llm_gateway.domain.routing import RoutingTable
from llm_gateway.settings import GatewaySettings


@dataclass(frozen=True, slots=True)
class GatewayWiring:
    settings: GatewaySettings
    residency: ResidencyPolicy
    providers: Mapping[str, LLMProvider]
    embedders: Mapping[str, EmbeddingProvider]
    ledger: CostLedger
    registry: PromptRegistry
    routing: RoutingTable
    complete: Complete
    embed: Embed
    usage: Usage
    checks: Sequence[tuple[str, Callable[[], bool]]]
    close: Callable[[], None]
