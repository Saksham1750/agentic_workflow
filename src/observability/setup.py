import logging

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME

from src.observability.exporters import SQLiteSpanExporter, SQLiteMetricExporter

logger = logging.getLogger(__name__)


def init_observability(app=None):
    resource = Resource.create(
        {
            SERVICE_NAME: "ai-agent-factory",
            "service.version": "2.0.0",
        }
    )

    span_exporter = SQLiteSpanExporter()
    span_processor = BatchSpanProcessor(span_exporter, max_queue_size=2048)
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(span_processor)
    trace.set_tracer_provider(tracer_provider)

    metric_exporter = SQLiteMetricExporter()
    metric_reader = PeriodicExportingMetricReader(
        metric_exporter, export_interval_millis=30_000
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(
                app, excluded_urls="docs,openapi.json,redoc"
            )
            logger.info("FastAPI auto-instrumentation enabled")
        except Exception as e:
            logger.warning("FastAPI instrumentation failed: %s", e)

    logger.info("OpenTelemetry initialized with SQLite exporters")


def shutdown_observability():
    try:
        tp = trace.get_tracer_provider()
        if isinstance(tp, TracerProvider):
            tp.shutdown()
    except Exception as e:
        logger.warning("TracerProvider shutdown failed: %s", e)

    try:
        mp = metrics.get_meter_provider()
        if isinstance(mp, MeterProvider):
            mp.shutdown()
    except Exception as e:
        logger.warning("MeterProvider shutdown failed: %s", e)
