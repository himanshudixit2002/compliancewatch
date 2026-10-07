"""Where the harness gets model answers from.

``scripted`` answers every case with its own label, which proves the scoring and the validators
end to end and must score 1.0. ``fake`` runs the llm-gateway in process with its deterministic
provider: no tokens, no network, the plumbing exercised the way CI runs it. ``gateway`` talks to
a running gateway over HTTP, which is how the nightly run reaches a real model (the gateway
holds the provider key; the harness never sees it).
"""

import json
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from decimal import Decimal

from fastapi.testclient import TestClient

from domain_kernel.protocols import LLMProvider
from llm_gateway.main import build_app
from llm_gateway.settings import GatewaySettings
from pipeline.infrastructure.gateway import GatewayProvider
from pipeline.label import GoldenCase
from pipeline.testing import ScriptedProvider

PROVIDERS = ("scripted", "fake", "gateway")


def scripted(cases: Sequence[GoldenCase]) -> ScriptedProvider:
    answers: dict[str | tuple[str, str], str] = {
        str(case.document.document_id): json.dumps(case.expected, default=str)
        for case in cases
        if case.expected is not None
    }
    return ScriptedProvider(answers)


@contextmanager
def gateway_client(completion_provider: LLMProvider | None = None) -> Iterator[TestClient]:
    """The gateway app in process: fake provider, memory ledger, no cache, the repo's prompt
    registry. ``completion_provider`` answers every completion in place of the fake (embeddings
    stay fake), so scripted answers still pass the registry check, the masking and the ledger.
    It runs under the ``global`` residency policy whatever ``CW_LLM_RESIDENCY`` says: nothing it
    serves leaves the process, and under ``india_only`` the gateway would refuse the scripted
    provider, which it does not know to run in India."""
    settings = GatewaySettings(
        _env_file=None,
        service_name="llm-gateway",
        llm_provider="fake",
        llm_residency="global",
        llm_ledger="memory",
        llm_cache_ttl_seconds=0,
        llm_feature_monthly_budget_inr=Decimal("100000"),
        llm_tenant_monthly_budget_inr=Decimal("100000"),
        langfuse_host=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )
    with TestClient(build_app(settings, completion_provider=completion_provider)) as client:
        yield client


@contextmanager
def fake_gateway() -> Iterator[GatewayProvider]:
    """The gateway app in process with its fake provider, as the pipeline's client sees it."""
    with gateway_client() as client:
        yield GatewayProvider(client=client, tenant_id=None)


@contextmanager
def http_gateway(base_url: str) -> Iterator[GatewayProvider]:
    provider = GatewayProvider(base_url)
    try:
        yield provider
    finally:
        provider.close()


ProviderFactory = Callable[[Sequence[GoldenCase]], "Iterator[LLMProvider]"]


@contextmanager
def provider_for(
    name: str, cases: Sequence[GoldenCase], *, gateway_url: str
) -> Iterator[LLMProvider]:
    if name == "scripted":
        yield scripted(cases)
    elif name == "fake":
        with fake_gateway() as provider:
            yield provider
    elif name == "gateway":
        with http_gateway(gateway_url) as provider:
            yield provider
    else:
        raise ValueError(f"unknown provider {name!r}; known: {', '.join(PROVIDERS)}")
