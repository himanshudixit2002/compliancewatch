"""A Temporal client built from settings."""

from collections.abc import Sequence

from temporalio.client import Client, Interceptor
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.contrib.pydantic import pydantic_data_converter

from py_common.settings import Settings


def default_interceptors() -> list[Interceptor]:
    """Tracing only; the span provider is whatever ``py_common.telemetry`` configured.

    Workflow and activity spans are created even when the starter carried no span (a schedule,
    the CLI, a script), so a worker always shows up in Tempo.
    """
    return [TracingInterceptor(always_create_workflow_spans=True)]


async def connect(
    settings: Settings, *, interceptors: Sequence[Interceptor] | None = None
) -> Client:
    """Connect to ``CW_TEMPORAL_ADDRESS`` in ``CW_TEMPORAL_NAMESPACE``.

    Pydantic models and dataclasses cross the wire through the pydantic data converter, so
    activity inputs and outputs are typed objects, never dicts.
    """
    return await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
        data_converter=pydantic_data_converter,
        interceptors=default_interceptors() if interceptors is None else list(interceptors),
    )
