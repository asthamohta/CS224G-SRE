"""
Synthetic OTLP trace, metric, and log fixtures for a database timeout scenario.

Models a cart-service request with a parent HTTP span and a slow, failing
database child span, plus a corresponding ERROR log. Intended for testing
OTel ingestion and downstream root-cause analysis.
"""

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest

import time
import random


def _kv(key, value):
    return KeyValue(key=key, value=AnyValue(string_value=str(value)))


def create_test_traces():
    req = ExportTraceServiceRequest()

    rs = req.resource_spans.add()
    rs.resource.attributes.append(_kv("service.name", "cart-service"))

    scope_spans = rs.scope_spans.add()

    trace_id = random.randbytes(16)
    parent_span_id = random.randbytes(8)
    child_span_id = random.randbytes(8)

    # parent span
    parent = scope_spans.spans.add()
    parent.trace_id = trace_id
    parent.span_id = parent_span_id
    parent.name = "HTTP GET /checkout"
    parent.start_time_unix_nano = int(time.time_ns())
    parent.end_time_unix_nano = parent.start_time_unix_nano + 50_000_000
    parent.status.code = 1  

    # child span (simulate DB timeout)
    child = scope_spans.spans.add()
    child.trace_id = trace_id
    child.span_id = child_span_id
    child.parent_span_id = parent_span_id
    child.name = "SELECT cart_items"
    child.start_time_unix_nano = parent.start_time_unix_nano + 5_000_000
    child.end_time_unix_nano = child.start_time_unix_nano + 5_000_000_000
    child.status.code = 2  # ERROR
    child.status.message = "Database timeout"

    child.attributes.append(_kv("db.system", "postgres"))
    child.attributes.append(_kv("exception.message", "Database connection timeout after 5000ms"))

    return req


def create_test_metrics():
    return ExportMetricsServiceRequest()


def create_test_logs():
    req = ExportLogsServiceRequest()

    rl = req.resource_logs.add()
    rl.resource.attributes.append(_kv("service.name", "cart-service"))

    scope_logs = rl.scope_logs.add()

    log = scope_logs.log_records.add()
    log.time_unix_nano = int(time.time_ns())
    log.severity_text = "ERROR"
    log.severity_number = 17
    log.body.string_value = "Database connection timeout after 5000ms"

    return req
