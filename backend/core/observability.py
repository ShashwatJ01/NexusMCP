from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor

from core.config import Settings
from core.logging_config import system_logger


def configure_observability(settings: Settings) -> None:
    """Configure OTel once and enable optional MCP and LangSmith instrumentation."""

    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.otel_service_name,
                "deployment.environment": settings.environment,
            }
        )
    )
    if settings.otel_exporter_otlp_endpoint is not None:
        exporter = OTLPSpanExporter(endpoint=str(settings.otel_exporter_otlp_endpoint))
        provider.add_span_processor(BatchSpanProcessor(exporter))
    if settings.enable_console_traces:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)

    try:
        from openinference.instrumentation.mcp import MCPInstrumentor

        MCPInstrumentor().instrument(tracer_provider=provider)
    except (ImportError, RuntimeError) as exc:
        system_logger(component="observability").warning(
            "MCP auto-instrumentation unavailable: {reason}", reason=str(exc)
        )

