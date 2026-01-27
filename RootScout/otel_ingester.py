# otel_ingester.py
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# OTLP protobuf messages (from opentelemetry-proto)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hex_or_none(b: bytes) -> Optional[str]:
    if not b:
        return None
    return b.hex()


def _any_value_to_python(v: Any) -> Any:
    """
    Converts OTLP AnyValue into a JSON-serializable python object.
    Handles the common scalar cases + arrays + kvlists.
    """
    which = v.WhichOneof("value")
    if which is None:
        return None

    if which == "string_value":
        return v.string_value
    if which == "bool_value":
        return v.bool_value
    if which == "int_value":
        return int(v.int_value)
    if which == "double_value":
        return float(v.double_value)
    if which == "bytes_value":
        return bytes(v.bytes_value).hex()

    if which == "array_value":
        return [_any_value_to_python(x) for x in v.array_value.values]

    if which == "kvlist_value":
        out: Dict[str, Any] = {}
        for kv in v.kvlist_value.values:
            out[kv.key] = _any_value_to_python(kv.value)
        return out

    # Fallback
    return str(v)


def _attrs_to_dict(attrs: List[Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for a in attrs:
        out[a.key] = _any_value_to_python(a.value)
    return out


class TelemetrySink:
    """
    Sink interface so you can swap persistence later.
    Later: write to Postgres / ClickHouse / Kafka, etc.
    """
    def emit(self, record: Dict[str, Any]) -> None:
        raise NotImplementedError


class PrintSink(TelemetrySink):
    def emit(self, record: Dict[str, Any]) -> None:
        print(record)


@dataclass(frozen=True)
class IngestResult:
    received_at: str
    kind: str
    count: int


class OTelIngester:
    def __init__(self, sink: TelemetrySink):
        self._sink = sink

    # -------- Traces --------
    def ingest_traces(self, req: ExportTraceServiceRequest) -> IngestResult:
        emitted = 0
        received_at = _now_utc_iso()

        for rs in req.resource_spans:
            resource_attrs = _attrs_to_dict(rs.resource.attributes)
            # Most important identity fields (best-effort)
            service_name = resource_attrs.get("service.name")
            service_version = resource_attrs.get("service.version")
            env = resource_attrs.get("deployment.environment.name")

            for scope_spans in rs.scope_spans:
                scope = scope_spans.scope
                scope_name = getattr(scope, "name", None)
                scope_version = getattr(scope, "version", None)

                for span in scope_spans.spans:
                    record = {
                        "received_at": received_at,
                        "signal": "trace",
                        "service": service_name,
                        "service_version": service_version,
                        "environment": env,
                        "scope_name": scope_name,
                        "scope_version": scope_version,
                        "trace_id": _hex_or_none(span.trace_id),
                        "span_id": _hex_or_none(span.span_id),
                        "parent_span_id": _hex_or_none(span.parent_span_id),
                        "name": span.name,
                        "kind": int(span.kind),
                        "start_time_unix_nano": int(span.start_time_unix_nano),
                        "end_time_unix_nano": int(span.end_time_unix_nano),
                        "status_code": int(span.status.code) if span.status else None,
                        "status_message": span.status.message if span.status else None,
                        "span_attributes": _attrs_to_dict(span.attributes),
                        # You can add events / links later
                    }
                    self._sink.emit(record)
                    emitted += 1

        return IngestResult(received_at=received_at, kind="traces", count=emitted)

    # -------- Metrics --------
    def ingest_metrics(self, req: ExportMetricsServiceRequest) -> IngestResult:
        emitted = 0
        received_at = _now_utc_iso()

        for rm in req.resource_metrics:
            resource_attrs = _attrs_to_dict(rm.resource.attributes)
            service_name = resource_attrs.get("service.name")
            service_version = resource_attrs.get("service.version")
            env = resource_attrs.get("deployment.environment.name")

            for scope_metrics in rm.scope_metrics:
                scope = scope_metrics.scope
                scope_name = getattr(scope, "name", None)
                scope_version = getattr(scope, "version", None)

                for metric in scope_metrics.metrics:
                    data_type = metric.WhichOneof("data")  # gauge, sum, histogram, etc.

                    # Minimal, safe "normalized" representation
                    metric_record = {
                        "received_at": received_at,
                        "signal": "metric",
                        "service": service_name,
                        "service_version": service_version,
                        "environment": env,
                        "scope_name": scope_name,
                        "scope_version": scope_version,
                        "name": metric.name,
                        "description": metric.description,
                        "unit": metric.unit,
                        "type": data_type,
                        "points": [],
                    }

                    # Extract points based on data type
                    if data_type == "gauge":
                        for p in metric.gauge.data_points:
                            metric_record["points"].append({
                                "time_unix_nano": int(p.time_unix_nano),
                                "start_time_unix_nano": int(p.start_time_unix_nano),
                                "attributes": _attrs_to_dict(p.attributes),
                                "value": _number_point_value(p),
                            })

                    elif data_type == "sum":
                        for p in metric.sum.data_points:
                            metric_record["points"].append({
                                "time_unix_nano": int(p.time_unix_nano),
                                "start_time_unix_nano": int(p.start_time_unix_nano),
                                "attributes": _attrs_to_dict(p.attributes),
                                "value": _number_point_value(p),
                            })

                    elif data_type == "histogram":
                        for p in metric.histogram.data_points:
                            metric_record["points"].append({
                                "time_unix_nano": int(p.time_unix_nano),
                                "start_time_unix_nano": int(p.start_time_unix_nano),
                                "attributes": _attrs_to_dict(p.attributes),
                                "count": int(p.count),
                                "sum": float(p.sum) if p.HasField("sum") else None,
                                "bucket_counts": [int(x) for x in p.bucket_counts],
                                "explicit_bounds": [float(x) for x in p.explicit_bounds],
                            })

                    else:
                        # Keep unknown types as raw string placeholder for now
                        metric_record["raw_note"] = "Metric type not yet expanded in Week 2 ingestion"

                    self._sink.emit(metric_record)
                    emitted += 1

        return IngestResult(received_at=received_at, kind="metrics", count=emitted)

    # -------- Logs --------
    def ingest_logs(self, req: ExportLogsServiceRequest) -> IngestResult:
        emitted = 0
        received_at = _now_utc_iso()

        for rl in req.resource_logs:
            resource_attrs = _attrs_to_dict(rl.resource.attributes)
            service_name = resource_attrs.get("service.name")
            service_version = resource_attrs.get("service.version")
            env = resource_attrs.get("deployment.environment.name")

            for scope_logs in rl.scope_logs:
                scope = scope_logs.scope
                scope_name = getattr(scope, "name", None)
                scope_version = getattr(scope, "version", None)

                for lr in scope_logs.log_records:
                    record = {
                        "received_at": received_at,
                        "signal": "log",
                        "service": service_name,
                        "service_version": service_version,
                        "environment": env,
                        "scope_name": scope_name,
                        "scope_version": scope_version,
                        "time_unix_nano": int(lr.time_unix_nano),
                        "observed_time_unix_nano": int(lr.observed_time_unix_nano),
                        "severity_text": lr.severity_text,
                        "severity_number": int(lr.severity_number),
                        "body": _any_value_to_python(lr.body),
                        "trace_id": _hex_or_none(lr.trace_id),
                        "span_id": _hex_or_none(lr.span_id),
                        "attributes": _attrs_to_dict(lr.attributes),
                    }
                    self._sink.emit(record)
                    emitted += 1

        return IngestResult(received_at=received_at, kind="logs", count=emitted)


def _number_point_value(point: Any) -> Any:
    """
    NumberDataPoint can store either an int or double value, depending on which is set.
    """
    which = point.WhichOneof("value")
    if which == "as_int":
        return int(point.as_int)
    if which == "as_double":
        return float(point.as_double)
    return None
