"""OpenTelemetry for services and workers (guide section 18).

``configure_telemetry`` installs a tracer and a meter provider that export over OTLP gRPC to
``CW_OTEL_ENDPOINT``; with the endpoint empty nothing is installed and every span and metric is
a no-op. ``instrument_app`` adds a span and the HTTP metrics per request, ``instrument_engine``
a span per SQL statement. Log lines carry ``trace_id`` and ``span_id`` through the structlog
processor in ``py_common.logging``, so a trace in Tempo and its log lines share an id.
"""

import os
import threading
from dataclasses import dataclass

# The HTTP instrumentations emit the stable semantic conventions (http.server.request.duration
# in seconds, http.route, http.response.status_code) only when this is set before they
# initialise; the Grafana dashboard queries those names. An operator may still override it.
os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy import Engine

from py_common.logging import add_trace_context, get_logger
from py_common.settings import Settings

log = get_logger(__name__)
EXCLUDED_URLS = "health,ready"
METRIC_EXPORT_INTERVAL_MS = 15_000
_install_lock = threading.Lock()
_installed: "Telemetry | None" = None


@dataclass(frozen=True, slots=True)
class Telemetry:
    """What was installed; ``enabled`` is False when no endpoint is configured."""

    enabled: bool
    service_name: str
    endpoint: str | None
    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None

    def shutdown(self) -> None:
        """Flush and stop the exporters; called from the app lifespan and the worker."""
        if self.tracer_provider is not None:
            self.tracer_provider.shutdown()
        if self.meter_provider is not None:
            self.meter_provider.shutdown()


def build_telemetry(*, service_name: str, version: str, settings: Settings) -> Telemetry:
    """Providers for the settings, not yet installed as the globals."""
    endpoint = (settings.otel_endpoint or "").strip() or None
    if endpoint is None:
        return Telemetry(enabled=False, service_name=service_name, endpoint=None)
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": version,
            "deployment.environment": settings.env,
        }
    )
    insecure = not endpoint.startswith("https://")
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=insecure))
    )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=endpoint, insecure=insecure),
                export_interval_millis=METRIC_EXPORT_INTERVAL_MS,
            )
        ],
    )
    return Telemetry(
        enabled=True,
        service_name=service_name,
        endpoint=endpoint,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
    )


def configure_telemetry(*, service_name: str, version: str, settings: Settings) -> Telemetry:
    """Install the providers as the process globals once; later calls return the first result.

    The OpenTelemetry API allows one global provider per process, so a test that builds several
    apps shares the first one. ``build_telemetry`` is the pure part for tests.
    """
    global _installed
    with _install_lock:
        if _installed is not None:
            return _installed
        telemetry = build_telemetry(service_name=service_name, version=version, settings=settings)
        if telemetry.enabled:
            trace.set_tracer_provider(telemetry.tracer_provider)  # type: ignore[arg-type]
            metrics.set_meter_provider(telemetry.meter_provider)  # type: ignore[arg-type]
            log.info("telemetry.enabled", endpoint=telemetry.endpoint, service=service_name)
        _installed = telemetry
        return telemetry


def instrument_app(app: FastAPI, telemetry: Telemetry) -> None:
    """A span and the HTTP duration metric per request; health probes are excluded."""
    if not telemetry.enabled:
        return
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=telemetry.tracer_provider,
        meter_provider=telemetry.meter_provider,
        excluded_urls=EXCLUDED_URLS,
    )


def instrument_engine(engine: Engine, telemetry: Telemetry) -> None:
    """A span per statement on a sync engine (an async engine passes ``engine.sync_engine``)."""
    if not telemetry.enabled:
        return
    SQLAlchemyInstrumentor().instrument(
        engine=engine,
        tracer_provider=telemetry.tracer_provider,
        skip_dep_check=True,  # the instrumentation's SQLAlchemy pin predates 2.1
    )


__all__ = [
    "Telemetry",
    "add_trace_context",
    "build_telemetry",
    "configure_telemetry",
    "instrument_app",
    "instrument_engine",
]
