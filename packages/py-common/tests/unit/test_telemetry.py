import io
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from py_common.app import create_app
from py_common.logging import configure_logging, get_logger
from py_common.settings import Settings
from py_common.telemetry import Telemetry, build_telemetry, instrument_app


def is_instrumented(app: FastAPI) -> bool:
    return bool(getattr(app, "_is_instrumented_by_opentelemetry", False))


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, service_name="t", **overrides)  # type: ignore[arg-type]


def test_no_endpoint_means_nothing_is_installed() -> None:
    telemetry = build_telemetry(service_name="t", version="0", settings=settings())
    assert telemetry == Telemetry(enabled=False, service_name="t", endpoint=None)
    telemetry.shutdown()


@pytest.mark.parametrize("endpoint", ["http://localhost:4317", "  http://localhost:4317  "])
def test_an_endpoint_builds_exporting_providers(endpoint: str) -> None:
    telemetry = build_telemetry(
        service_name="svc", version="1.2.3", settings=settings(otel_endpoint=endpoint)
    )
    assert telemetry.enabled
    assert telemetry.endpoint == "http://localhost:4317"
    assert telemetry.tracer_provider is not None
    assert telemetry.meter_provider is not None
    attributes = telemetry.tracer_provider.resource.attributes
    assert attributes["service.name"] == "svc"
    assert attributes["service.version"] == "1.2.3"
    assert attributes["deployment.environment"] == "local"
    telemetry.shutdown()


def test_disabled_telemetry_leaves_the_app_alone() -> None:
    app = create_app(service_name="t", version="0", settings=settings())
    assert app.state.telemetry.enabled is False
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert not is_instrumented(app)


def test_instrument_app_instruments_when_enabled() -> None:
    telemetry = build_telemetry(
        service_name="t", version="0", settings=settings(otel_endpoint="http://localhost:4317")
    )
    app = create_app(service_name="t", version="0", settings=settings())
    instrument_app(app, telemetry)
    assert is_instrumented(app)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    telemetry.shutdown()


def test_log_lines_carry_the_span_ids_inside_a_span() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    buffer = io.StringIO()
    configure_logging(service_name="t", stream=buffer)
    logger = get_logger("py_common.tests")
    logger.info("outside")
    with provider.get_tracer("t").start_as_current_span("work") as span:
        logger.info("inside")
    lines = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
    assert "trace_id" not in lines[0]
    context = span.get_span_context()
    assert lines[1]["trace_id"] == format(context.trace_id, "032x")
    assert lines[1]["span_id"] == format(context.span_id, "016x")
