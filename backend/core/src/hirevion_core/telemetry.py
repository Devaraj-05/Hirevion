"""OpenTelemetry for every backend service: traces, metrics and logs over OTLP/HTTP (ADR-0010).

Locally the collector is Grafana's otel-lgtm (`uv run hv up --obs`, OTLP on 127.0.0.1:4318). It
is off unless `OTEL_SDK_DISABLED=false`, so a stack without the obs profile logs no export
errors. Span attributes never hold SQL parameter values or Valkey command arguments, and exported
logs pass through the same redaction as stdout.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from opentelemetry import metrics as otel_metrics
from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy.engine import EngineTracer
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.logging import RedactingFilter
from hirevion_core.settings import repo_env_file

METRIC_EXPORT_INTERVAL_MS = 60_000


class TelemetrySettings(BaseSettings):
    """The standard OTel variables Hirevion uses, plus the deployment environment."""

    model_config = SettingsConfigDict(extra="ignore")

    otel_sdk_disabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://127.0.0.1:4318"
    hv_environment: str = "development"


def load_telemetry_settings() -> TelemetrySettings:
    return TelemetrySettings(_env_file=repo_env_file())  # type: ignore[call-arg]


@dataclass
class Telemetry:
    enabled: bool
    tracer_provider: trace.TracerProvider
    meter_provider: otel_metrics.MeterProvider
    logger_provider: LoggerProvider | None = None
    _shutdowns: list[Callable[[], object]] = field(default_factory=list)

    def shutdown(self) -> None:
        """Flush and stop the exporters (once, at process exit)."""
        for shutdown in reversed(self._shutdowns):
            shutdown()
        self._shutdowns.clear()


def setup_telemetry(
    service_name: str,
    *,
    service_version: str = "unknown",
    settings: TelemetrySettings | None = None,
    span_exporter: SpanExporter | None = None,
    metrics: bool = True,
    logs: bool = True,
    set_global: bool = True,
) -> Telemetry:
    """Providers for `service_name`. `span_exporter` replaces OTLP (tests); `set_global` also
    installs them as the process defaults and instruments Valkey."""
    settings = settings or load_telemetry_settings()
    if settings.otel_sdk_disabled:
        return Telemetry(False, trace.NoOpTracerProvider(), otel_metrics.NoOpMeterProvider())

    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment": settings.hv_environment,
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        SimpleSpanProcessor(span_exporter)
        if span_exporter is not None
        else BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    telemetry = Telemetry(True, tracer_provider, otel_metrics.NoOpMeterProvider())
    telemetry._shutdowns.append(tracer_provider.shutdown)

    if metrics:
        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
            export_interval_millis=METRIC_EXPORT_INTERVAL_MS,
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        telemetry.meter_provider = meter_provider
        telemetry._shutdowns.append(meter_provider.shutdown)

    if logs:
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"))
        )
        handler = LoggingHandler(logger_provider=logger_provider)
        handler.addFilter(RedactingFilter())
        root = logging.getLogger()
        root.addHandler(handler)
        telemetry.logger_provider = logger_provider
        telemetry._shutdowns.append(logger_provider.shutdown)
        telemetry._shutdowns.append(lambda: root.removeHandler(handler))

    if set_global:
        trace.set_tracer_provider(tracer_provider)
        otel_metrics.set_meter_provider(telemetry.meter_provider)
        if telemetry.logger_provider is not None:
            set_logger_provider(telemetry.logger_provider)
        RedisInstrumentor().instrument(tracer_provider=tracer_provider)
    return telemetry


def instrument_engine(engine: AsyncEngine, telemetry: Telemetry) -> None:
    """Trace `engine`'s queries (statements only; parameter values are never recorded)."""
    if not telemetry.enabled:
        return
    scope = "opentelemetry.instrumentation.sqlalchemy"
    connections = telemetry.meter_provider.get_meter(scope).create_up_down_counter(
        "db.client.connections.usage", unit="connections", description="Connections in use"
    )
    EngineTracer(  # type: ignore[no-untyped-call]
        telemetry.tracer_provider.get_tracer(scope), engine.sync_engine, connections
    )
