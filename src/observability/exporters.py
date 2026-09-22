import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Sequence

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult, ReadableSpan
from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult, MetricsData

from src.config import get_settings


class SQLiteSpanExporter(SpanExporter):
    def __init__(self):
        self._shutdown = False

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if self._shutdown:
            return SpanExportResult.FAILURE
        try:
            self._write_spans(spans)
            return SpanExportResult.SUCCESS
        except Exception:
            return SpanExportResult.FAILURE

    def _write_spans(self, spans: Sequence[ReadableSpan]):
        settings = get_settings()
        conn = sqlite3.connect(settings.SQLITE_DB_PATH)
        try:
            cursor = conn.cursor()
            for span in spans:
                trace_id = format(span.get_span_id() >> 64, "032x") if span.get_span_id() else ""
                span_id_hex = format(span.get_span_id(), "016x") if span.get_span_id() else ""

                parent_id = ""
                parent_ctx = span.parent
                if parent_ctx and parent_ctx.span_id:
                    parent_id = format(parent_ctx.span_id, "016x")

                start_dt = datetime.fromtimestamp(span.start_time / 1e9, tz=timezone.utc) if span.start_time else datetime.now(timezone.utc)
                end_dt = datetime.fromtimestamp(span.end_time / 1e9, tz=timezone.utc) if span.end_time else None

                attrs = dict(span.attributes) if span.attributes else {}
                raw_trace_id = format(span.context.trace_id, "032x") if span.context else ""
                raw_span_id = format(span.context.span_id, "016x") if span.context else ""

                project_id = attrs.pop("project.id", None) or attrs.pop("project_id", None)
                run_id = attrs.pop("run.id", None) or attrs.pop("run_id", None)

                otel_events = []
                for e in (span.events or []):
                    otel_events.append({
                        "name": e.name,
                        "timestamp": e.timestamp,
                        "attributes": dict(e.attributes) if e.attributes else {},
                    })

                status_code = "OK"
                status_msg = ""
                if span.status:
                    status_code = span.status.name or "OK"
                    status_msg = span.status.description or ""

                cursor.execute(
                    """INSERT INTO trace_spans
                    (id, trace_id, span_id, parent_span_id, name, kind, start_time, end_time,
                     status_code, status_message, attributes, events, project_id, run_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        raw_trace_id,
                        raw_span_id,
                        parent_id,
                        span.name,
                        span.kind.name if span.kind else "INTERNAL",
                        start_dt.isoformat(),
                        end_dt.isoformat() if end_dt else None,
                        status_code,
                        status_msg,
                        attrs if attrs else None,
                        otel_events if otel_events else None,
                        project_id,
                        run_id,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def shutdown(self, timeout_millis: float = 30000, **kwargs):
        self._shutdown = True

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


class SQLiteMetricExporter(MetricExporter):
    def __init__(self):
        super().__init__()
        self._shutdown = False

    def export(self, metrics_data: MetricsData, timeout_millis: float = 10_000, **kwargs) -> MetricExportResult:
        if self._shutdown:
            return MetricExportResult.FAILURE
        try:
            self._write_metrics(metrics_data)
            return MetricExportResult.SUCCESS
        except Exception:
            return MetricExportResult.FAILURE

    def _write_metrics(self, metrics_data: MetricsData):
        settings = get_settings()
        conn = sqlite3.connect(settings.SQLITE_DB_PATH)
        try:
            cursor = conn.cursor()
            for resource_metrics in metrics_data.resource_metrics:
                for scope_metrics in resource_metrics.scope_metrics:
                    for metric in scope_metrics.metrics:
                        metric_name = metric.name
                        unit = metric.unit or ""

                        data_points = []
                        if hasattr(metric.data, "data_points"):
                            data_points = metric.data.data_points

                        for dp in data_points:
                            value = 0.0
                            if hasattr(dp, "value"):
                                value = float(dp.value)
                            elif hasattr(dp, "sum"):
                                value = float(dp.sum)
                            elif hasattr(dp, "count"):
                                value = float(dp.count)

                            ts_nanos = getattr(dp, "time_unix_nano", None)
                            timestamp = datetime.fromtimestamp(ts_nanos / 1e9, tz=timezone.utc) if ts_nanos else datetime.now(timezone.utc)

                            attrs = dict(dp.attributes) if hasattr(dp, "attributes") and dp.attributes else {}
                            project_id = attrs.pop("project.id", None) or attrs.pop("project_id", None)
                            run_id = attrs.pop("run.id", None) or attrs.pop("run_id", None)

                            cursor.execute(
                                """INSERT INTO metric_records
                                (id, metric_name, value, unit, attributes, timestamp, project_id, run_id, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (
                                    str(uuid.uuid4()),
                                    metric_name,
                                    value,
                                    unit,
                                    attrs if attrs else None,
                                    timestamp.isoformat(),
                                    project_id,
                                    run_id,
                                    datetime.now(timezone.utc).isoformat(),
                                ),
                            )
            conn.commit()
        finally:
            conn.close()

    def shutdown(self, timeout_millis: float = 30000, **kwargs):
        self._shutdown = True

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
