"""OpenTelemetry for services and workers (guide section 18).

``configure_telemetry`` installs a tracer and a meter provider that export over OTLP to
``CW_OTEL_ENDPOINT``; with the endpoint empty nothing is installed and every span and metric is
a no-op. The transport is ``CW_OTEL_PROTOCOL``: gRPC to the endpoint itself, or HTTP/protobuf to
``<endpoint>/v1/traces`` and ``<endpoint>/v1/metrics``, the form managed gateways such as Grafana
Cloud's take. Every export carries ``CW_OTEL_HEADERS`` (their credentials). ``instrument_app``
adds a span and the HTTP metrics per request, ``instrument_engine`` a span per SQL statement. Log
lines carry ``trace_id`` and ``span_id`` through the structlog processor in
``py_common.logging``, so a trace in Tempo and its log lines share an id.
"""

import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field

# The HTTP instrumentations emit the stable semantic conventions (http.server.request.duration
# in seconds, http.route, http.response.status_code) only when this is set before they
# initialise; the Grafana dashboard queries those names. An operator may still override it.
os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
    OTLPMetricExporter as GrpcMetricExporter,
)
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter as GrpcSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter as HttpMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as HttpSpanExporter,
)
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from sqlalchemy import Engine

from py_common.logging import add_trace_context, get_logger
from py_common.settings import OtelProtocol, Settings

log = get_logger(__name__)
EXCLUDED_URLS = "health,ready"
METRIC_EXPORT_INTERVAL_MS = 15_000
_install_lock = threading.Lock()
_installed: "Telemetry | None" = None


class _Once:
    """True for the first caller of ``first`` only, across threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._done = False

    def first(self) -> bool:
        with self._lock:
            if self._done:
                return False
            self._done = True
            return True


@dataclass(frozen=True, slots=True)
class Telemetry:
    """What was installed; ``enabled`` is False when no endpoint is configured."""

    enabled: bool
    service_name: str
    endpoint: str | None
    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None
    _shutdown: _Once = field(default_factory=_Once, compare=False, repr=False)

    def shutdown(self) -> None:
        """Flush and stop the exporters; called from the app lifespan and the worker. Only the
        first call does anything, so every app of a process that hosts several may call it."""
        if not self._shutdown.first():
            return
        if self.tracer_provider is not None:
            self.tracer_provider.shutdown()
        if self.meter_provider is not None:
            self.meter_provider.shutdown()


@dataclass(frozen=True, slots=True)
class OtlpTarget:
    """Where and how the exporters send: the protocol, one URL per signal, the headers."""

    protocol: OtelProtocol
    traces_endpoint: str
    metrics_endpoint: str
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    insecure: bool = False
    """For gRPC: a plain connection, for an endpoint that is not ``https://``."""


def otlp_target(settings: Settings) -> OtlpTarget | None:
    """The export target the settings name; None when ``CW_OTEL_ENDPOINT`` is empty."""
    endpoint = (settings.otel_endpoint or "").strip() or None
    if endpoint is None:
        return None
    headers = settings.otel_header_map
    if settings.otel_protocol == "http/protobuf":
        base = endpoint.rstrip("/")
        return OtlpTarget(
            protocol="http/protobuf",
            traces_endpoint=f"{base}/v1/traces",
            metrics_endpoint=f"{base}/v1/metrics",
            headers=headers,
        )
    return OtlpTarget(
        protocol="grpc",
        traces_endpoint=endpoint,
        metrics_endpoint=endpoint,
        headers=headers,
        insecure=not endpoint.startswith("https://"),
    )


def span_exporter(target: OtlpTarget) -> SpanExporter:
    headers = dict(target.headers) or None
    if target.protocol == "http/protobuf":
        return HttpSpanExporter(endpoint=target.traces_endpoint, headers=headers)
    return GrpcSpanExporter(
        endpoint=target.traces_endpoint, insecure=target.insecure, headers=headers
    )


def metric_exporter(target: OtlpTarget) -> MetricExporter:
    headers = dict(target.headers) or None
    if target.protocol == "http/protobuf":
        return HttpMetricExporter(endpoint=target.metrics_endpoint, headers=headers)
    return GrpcMetricExporter(
        endpoint=target.metrics_endpoint, insecure=target.insecure, headers=headers
    )


def build_telemetry(*, service_name: str, version: str, settings: Settings) -> Telemetry:
    """Providers for the settings, not yet installed as the globals."""
    target = otlp_target(settings)
    if target is None:
        return Telemetry(enabled=False, service_name=service_name, endpoint=None)
    endpoint = (settings.otel_endpoint or "").strip()
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": version,
            "deployment.environment": settings.env,
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter(target)))
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                metric_exporter(target), export_interval_millis=METRIC_EXPORT_INTERVAL_MS
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
            log.info(
                "telemetry.enabled",
                endpoint=telemetry.endpoint,
                protocol=settings.otel_protocol,
                service=service_name,
            )
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
    "OtlpTarget",
    "Telemetry",
    "add_trace_context",
    "build_telemetry",
    "configure_telemetry",
    "instrument_app",
    "instrument_engine",
    "metric_exporter",
    "otlp_target",
    "span_exporter",
]
