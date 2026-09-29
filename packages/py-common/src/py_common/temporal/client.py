"""A Temporal client built from settings.

The dev stack's Temporal takes plain connections. Temporal Cloud takes an API key
(``CW_TEMPORAL_API_KEY``) over TLS, or a client certificate and its private key
(``CW_TEMPORAL_TLS_CERT`` and ``CW_TEMPORAL_TLS_KEY``, PEM text) for mutual TLS.
"""

from collections.abc import Sequence

from temporalio.client import Client, Interceptor
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import TLSConfig

from py_common.settings import Settings


def default_interceptors() -> list[Interceptor]:
    """Tracing only; the span provider is whatever ``py_common.telemetry`` configured.

    Workflow and activity spans are created even when the starter carried no span (a schedule,
    the CLI, a script), so a worker always shows up in Tempo.
    """
    return [TracingInterceptor(always_create_workflow_spans=True)]


def api_key(settings: Settings) -> str | None:
    """``CW_TEMPORAL_API_KEY``, or None when it is empty."""
    key = settings.temporal_api_key
    value = "" if key is None else key.get_secret_value()
    return value or None


def tls_config(settings: Settings) -> bool | TLSConfig:
    """What ``Client.connect`` takes as ``tls``: the client certificate and its key for mutual
    TLS, otherwise whether TLS is on (``Settings.temporal_tls_enabled``)."""
    cert, key = settings.temporal_tls_cert, settings.temporal_tls_key
    if cert is not None and key is not None and cert.get_secret_value():
        return TLSConfig(
            client_cert=cert.get_secret_value().encode("utf-8"),
            client_private_key=key.get_secret_value().encode("utf-8"),
        )
    return settings.temporal_tls_enabled


async def connect(
    settings: Settings, *, interceptors: Sequence[Interceptor] | None = None
) -> Client:
    """Connect to ``CW_TEMPORAL_ADDRESS`` in ``CW_TEMPORAL_NAMESPACE``, with the API key or the
    client certificate when one is configured.

    Pydantic models and dataclasses cross the wire through the pydantic data converter, so
    activity inputs and outputs are typed objects, never dicts.
    """
    return await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        api_key=api_key(settings),
        tls=tls_config(settings),
        data_converter=pydantic_data_converter,
        interceptors=default_interceptors() if interceptors is None else list(interceptors),
    )
