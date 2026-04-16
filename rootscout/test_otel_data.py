"""
test_otel_data.py - Generate synthetic OTLP data for testing

Creates realistic OpenTelemetry Protocol (OTLP) traces, metrics, and logs
for the e-commerce cart-service failure scenario.
"""

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest

from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span, Status
from opentelemetry.proto.metrics.v1.metrics_pb2 import ResourceMetrics, ScopeMetrics, Metric
from opentelemetry.proto.logs.v1.logs_pb2 import ResourceLogs, ScopeLogs, LogRecord
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.common.v1.common_pb2 import KeyValue, AnyValue, InstrumentationScope

import time
import random


def _kv(key: str, value: str) -> KeyValue:
    """Helper to create a string KeyValue attribute."""
    return KeyValue(key=key, value=AnyValue(string_value=value))


def _kv_int(key: str, value: int) -> KeyValue:
    """Helper to create an int KeyValue attribute."""
    return KeyValue(key=key, value=AnyValue(int_value=value))


def _kv_bool(key: str, value: bool) -> KeyValue:
    """Helper to create a bool KeyValue attribute."""
    return KeyValue(key=key, value=AnyValue(bool_value=value))


def _kv_double(key: str, value: float) -> KeyValue:
    """Helper to create a double KeyValue attribute."""
    return KeyValue(key=key, value=AnyValue(double_value=value))


def create_test_traces() -> ExportTraceServiceRequest:
    """
    Create synthetic trace data showing:
    - frontend -> auth-service (success)
    - frontend -> cart-service (error - database timeout)
    - cart-service -> database (timeout)
    """

    now_ns = int(time.time() * 1e9)

    # Trace IDs (same trace across all services)
    trace_id = bytes.fromhex("1234567890abcdef1234567890abcdef")

    # Span IDs
    frontend_span_id = bytes.fromhex("1111111111111111")
    auth_span_id = bytes.fromhex("2222222222222222")
    cart_span_id = bytes.fromhex("3333333333333333")
    db_span_id = bytes.fromhex("4444444444444444")

    # ===== Frontend Service =====
    frontend_resource = Resource(attributes=[
        _kv("service.name", "frontend"),
        _kv("service.version", "1.2.3"),
        _kv("deployment.environment.name", "production"),
    ])

    frontend_span = Span(
        trace_id=trace_id,
        span_id=frontend_span_id,
        name="GET /checkout",
        kind=Span.SPAN_KIND_SERVER,
        start_time_unix_nano=now_ns - int(6e9),  # 6 seconds ago
        end_time_unix_nano=now_ns - int(1e9),    # 1 second ago
        status=Status(code=Status.STATUS_CODE_ERROR, message="Internal Server Error"),
        attributes=[
            _kv("http.method", "GET"),
            _kv("http.route", "/checkout"),
            _kv("http.status_code", "500"),
            _kv("user.id", "user-12345"),
        ]
    )

    frontend_spans = ResourceSpans(
        resource=frontend_resource,
        scope_spans=[ScopeSpans(
            scope=InstrumentationScope(name="opentelemetry.instrumentation.flask"),
            spans=[frontend_span]
        )]
    )

    # ===== Auth Service (healthy) =====
    auth_resource = Resource(attributes=[
        _kv("service.name", "auth-service"),
        _kv("service.version", "2.1.0"),
        _kv("deployment.environment.name", "production"),
    ])

    auth_span = Span(
        trace_id=trace_id,
        span_id=auth_span_id,
        parent_span_id=frontend_span_id,
        name="POST /auth/verify",
        kind=Span.SPAN_KIND_SERVER,
        start_time_unix_nano=now_ns - int(5.9e9),
        end_time_unix_nano=now_ns - int(5.8e9),  # 100ms duration
        status=Status(code=Status.STATUS_CODE_OK),
        attributes=[
            _kv("http.method", "POST"),
            _kv("http.route", "/auth/verify"),
            _kv("http.status_code", "200"),
            _kv("user.id", "user-12345"),
        ]
    )

    auth_spans = ResourceSpans(
        resource=auth_resource,
        scope_spans=[ScopeSpans(
            scope=InstrumentationScope(name="opentelemetry.instrumentation.flask"),
            spans=[auth_span]
        )]
    )

    # ===== Cart Service (ERROR - timeout) =====
    cart_resource = Resource(attributes=[
        _kv("service.name", "cart-service"),
        _kv("service.version", "1.5.2"),
        _kv("deployment.environment.name", "production"),
    ])

    cart_span = Span(
        trace_id=trace_id,
        span_id=cart_span_id,
        parent_span_id=frontend_span_id,
        name="GET /cart/items",
        kind=Span.SPAN_KIND_SERVER,
        start_time_unix_nano=now_ns - int(5.7e9),
        end_time_unix_nano=now_ns - int(0.7e9),  # 5 second duration (timeout!)
        status=Status(code=Status.STATUS_CODE_ERROR, message="Database timeout"),
        attributes=[
            _kv("http.method", "GET"),
            _kv("http.route", "/cart/items"),
            _kv("http.status_code", "504"),
            _kv("user.id", "user-12345"),
            _kv("error", "true"),
            _kv("error.type", "DatabaseTimeoutError"),
            _kv("error.message", "Connection pool exhausted - timeout waiting for available connection"),
        ]
    )

    # Database query span (child of cart-service)
    db_span = Span(
        trace_id=trace_id,
        span_id=db_span_id,
        parent_span_id=cart_span_id,
        name="SELECT cart_items",
        kind=Span.SPAN_KIND_CLIENT,
        start_time_unix_nano=now_ns - int(5.6e9),
        end_time_unix_nano=now_ns - int(0.6e9),  # 5 second timeout
        status=Status(code=Status.STATUS_CODE_ERROR, message="Query timeout"),
        attributes=[
            _kv("db.system", "postgresql"),
            _kv("db.name", "ecommerce"),
            _kv("db.operation", "SELECT"),
            _kv("db.statement", "SELECT * FROM cart_items WHERE user_id = $1"),
            _kv("error", "true"),
            _kv("error.type", "TimeoutError"),
        ]
    )

    cart_spans = ResourceSpans(
        resource=cart_resource,
        scope_spans=[ScopeSpans(
            scope=InstrumentationScope(name="opentelemetry.instrumentation.flask"),
            spans=[cart_span, db_span]
        )]
    )

    return ExportTraceServiceRequest(resource_spans=[
        frontend_spans,
        auth_spans,
        cart_spans
    ])


def create_test_metrics() -> ExportMetricsServiceRequest:
    """
    Create synthetic metrics showing:
    - cart-service high error rate
    - cart-service high latency
    - auth-service healthy metrics
    """

    now_ns = int(time.time() * 1e9)

    # ===== Cart Service Metrics (degraded) =====
    cart_resource = Resource(attributes=[
        _kv("service.name", "cart-service"),
        _kv("service.version", "1.5.2"),
    ])

    # Error rate metric (15% errors)
    error_rate_metric = Metric(
        name="http.server.request.error_rate",
        description="Percentage of failed requests",
        unit="%",
    )

    # Note: Creating metrics requires more complex protobuf setup
    # For simplicity, we'll keep this minimal

    cart_metrics = ResourceMetrics(
        resource=cart_resource,
        scope_metrics=[ScopeMetrics(
            scope=InstrumentationScope(name="opentelemetry.instrumentation.flask"),
            metrics=[]  # Simplified for demo
        )]
    )

    return ExportMetricsServiceRequest(resource_metrics=[cart_metrics])


def create_test_logs() -> ExportLogsServiceRequest:
    """
    Create synthetic logs showing database connection pool errors from cart-service.
    """

    now_ns = int(time.time() * 1e9)

    cart_resource = Resource(attributes=[
        _kv("service.name", "cart-service"),
        _kv("service.version", "1.5.2"),
        _kv("deployment.environment.name", "production"),
    ])

    # Error log from cart-service
    error_log = LogRecord(
        time_unix_nano=now_ns - int(2e9),
        severity_number=17,  # ERROR
        severity_text="ERROR",
        body=AnyValue(string_value="DatabaseTimeoutError: Connection pool exhausted - timeout waiting for available connection (pool_size=10, active=10, idle=0)"),
        attributes=[
            _kv("log.logger", "cart_service.database"),
            _kv("error.type", "DatabaseTimeoutError"),
            _kv("db.pool.size", "10"),
            _kv("db.pool.active", "10"),
            _kv("db.pool.idle", "0"),
            _kv("user.id", "user-12345"),
        ],
        trace_id=bytes.fromhex("1234567890abcdef1234567890abcdef"),
        span_id=bytes.fromhex("3333333333333333"),
    )

    # Warning log (earlier)
    warning_log = LogRecord(
        time_unix_nano=now_ns - int(10e9),
        severity_number=13,  # WARN
        severity_text="WARN",
        body=AnyValue(string_value="Database connection pool nearing capacity: 9/10 connections in use"),
        attributes=[
            _kv("log.logger", "cart_service.database"),
            _kv("db.pool.size", "10"),
            _kv("db.pool.active", "9"),
        ],
    )

    cart_logs = ResourceLogs(
        resource=cart_resource,
        scope_logs=[ScopeLogs(
            scope=InstrumentationScope(name="cart-service"),
            log_records=[warning_log, error_log]
        )]
    )

    return ExportLogsServiceRequest(resource_logs=[cart_logs])
