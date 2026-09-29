from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from hirevion_core.telemetry import TelemetrySettings, setup_telemetry


def test_a_disabled_sdk_exports_nothing() -> None:
    telemetry = setup_telemetry(
        "hirevion-test", settings=TelemetrySettings(otel_sdk_disabled=True), set_global=False
    )
    assert telemetry.enabled is False
    with telemetry.tracer_provider.get_tracer("test").start_as_current_span("work") as span:
        assert not span.get_span_context().is_valid
    telemetry.shutdown()


def test_spans_reach_the_exporter_with_the_service_resource() -> None:
    exporter = InMemorySpanExporter()
    telemetry = setup_telemetry(
        "hirevion-test",
        service_version="1.2.3",
        settings=TelemetrySettings(hv_environment="test"),
        span_exporter=exporter,
        metrics=False,
        logs=False,
        set_global=False,
    )
    with telemetry.tracer_provider.get_tracer("test").start_as_current_span("work"):
        pass
    telemetry.shutdown()

    [span] = exporter.get_finished_spans()
    assert span.name == "work"
    assert span.resource.attributes["service.name"] == "hirevion-test"
    assert span.resource.attributes["service.version"] == "1.2.3"
    assert span.resource.attributes["deployment.environment"] == "test"
