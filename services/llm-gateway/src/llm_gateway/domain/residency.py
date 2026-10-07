"""Where a model call may send text: the residency policy (``CW_LLM_RESIDENCY``, ADR-020).

- ``global`` (the default): the masked text may reach a model outside India, through a provider
  asked for zero data retention. Every real call does today, since no routed model runs
  inference in India.
- ``india_only``: no text leaves India for a model call. A call reaches only a provider that runs
  in India, which today is the fake one alone, serving ``fake/...`` models in process; every other
  provider is refused with ``ResidencyUnavailableError`` (503 ``llm-residency-unavailable``)
  before it is called (``infrastructure.providers.residency``).

Which of the two the product runs under is the maintainer's decision, taken with counsel
(ADR-020, Proposed).
"""

from enum import StrEnum


class ResidencyPolicy(StrEnum):
    GLOBAL = "global"
    INDIA_ONLY = "india_only"

    @property
    def real_models_allowed(self) -> bool:
        """Whether a call may reach a real model; every routed one runs outside India today."""
        return self is ResidencyPolicy.GLOBAL
