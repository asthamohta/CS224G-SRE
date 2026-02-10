"""
test_otel_data.py
Generates synthetic OTLP (OpenTelemetry Protocol) data for testing.
Creates realistic traces, metrics, and logs in protobuf format.
"""

import time
import random
from typing import List, Tuple

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest

from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span, Status
from opentelemetry.proto.metrics.v1.metrics_pb2 import (
    ResourceMetrics, ScopeMetrics, Metric, Gauge, Sum, NumberDataPoint,
    AggregationTemporality
)
from opentelemetry.proto.logs.v1.logs_pb2 import ResourceLogs, ScopeLogs, LogRecord, SeverityNumber
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.common.v1.common_pb2 import KeyValue, AnyValue, InstrumentationScope


def make_attribute(key: str, value) -> KeyValue:
    """Helper to create OTLP KeyValue attribute."""
    kv = KeyValue(key=key)
    if isinstance(value, str):
        kv.value.string_value = value
    elif isinstance(value, int):
        kv.value.int_value = value
    elif isinstance(value, float):
        kv.value.double_value = value
    elif isinstance(value, bool):
        kv.value.bool_value = value
    return kv


def make_resource(service_name: str, service_version: str = "1.0.0", env: str = "production") -> Resource:
    """Creates an OTLP Resource with service metadata."""
    return Resource(
        attributes=[
            make_attribute("service.name", service_name),
            make_attribute("service.version", service_version),
            make_attribute("deployment.environment.name", env),
        ]
    )


def generate_trace_id() -> bytes:
    """Generate a random 16-byte trace ID."""
    return random.randbytes(16)


def generate_span_id() -> bytes:
    """Generate a random 8-byte span ID."""
    return random.randbytes(8)


def create_test_traces() -> ExportTraceServiceRequest:
    """
    Creates synthetic trace data representing a microservices call chain:

    frontend -> auth-service -> database
                 ↓
               cart-service (ERROR)
    """
    now_nano = time.time_ns()
    trace_id = generate_trace_id()

    # Span 1: Frontend (root span)
    frontend_span_id = generate_span_id()
    frontend_span = Span(
        trace_id=trace_id,
        span_id=frontend_span_id,
        parent_span_id=b"",  # Root span has no parent
        name="GET /checkout",
        kind=Span.SPAN_KIND_SERVER,
        start_time_unix_nano=now_nano,
        end_time_unix_nano=now_nano + 150_000_000,  # 150ms
        status=Status(code=Status.STATUS_CODE_OK),
        attributes=[
            make_attribute("http.method", "GET"),
            make_attribute("http.route", "/checkout"),
            make_attribute("http.status_code", 200),
        ],
    )

    # Span 2: Auth service (child of frontend)
    auth_span_id = generate_span_id()
    auth_span = Span(
        trace_id=trace_id,
        span_id=auth_span_id,
        parent_span_id=frontend_span_id,
        name="POST /auth/verify",
        kind=Span.SPAN_KIND_CLIENT,
        start_time_unix_nano=now_nano + 10_000_000,  # 10ms after frontend start
        end_time_unix_nano=now_nano + 60_000_000,    # 50ms duration
        status=Status(code=Status.STATUS_CODE_OK),
        attributes=[
            make_attribute("peer.service", "auth-service"),
            make_attribute("http.method", "POST"),
        ],
    )

    # Span 3: Cart service (child of frontend) - HAS ERROR
    cart_span_id = generate_span_id()
    cart_span = Span(
        trace_id=trace_id,
        span_id=cart_span_id,
        parent_span_id=frontend_span_id,
        name="GET /cart/items",
        kind=Span.SPAN_KIND_CLIENT,
        start_time_unix_nano=now_nano + 70_000_000,  # 70ms after frontend start
        end_time_unix_nano=now_nano + 140_000_000,   # 70ms duration
        status=Status(code=Status.STATUS_CODE_ERROR, message="Database connection timeout"),
        attributes=[
            make_attribute("peer.service", "cart-service"),
            make_attribute("http.method", "GET"),
            make_attribute("http.status_code", 500),
            make_attribute("error", True),
        ],
    )

    # Span 4: Database (child of auth)
    db_span_id = generate_span_id()
    db_span = Span(
        trace_id=trace_id,
        span_id=db_span_id,
        parent_span_id=auth_span_id,
        name="SELECT users WHERE id=?",
        kind=Span.SPAN_KIND_CLIENT,
        start_time_unix_nano=now_nano + 20_000_000,
        end_time_unix_nano=now_nano + 50_000_000,  # 30ms
        status=Status(code=Status.STATUS_CODE_OK),
        attributes=[
            make_attribute("peer.service", "database"),
            make_attribute("db.system", "postgresql"),
        ],
    )

    # Package into OTLP request
    request = ExportTraceServiceRequest()

    # Frontend service resource spans
    frontend_rs = ResourceSpans(
        resource=make_resource("frontend", "2.1.0"),
        scope_spans=[
            ScopeSpans(
                scope=InstrumentationScope(name="opentelemetry-python", version="1.20.0"),
                spans=[frontend_span],
            )
        ],
    )

    # Auth service resource spans
    auth_rs = ResourceSpans(
        resource=make_resource("auth-service", "1.5.2"),
        scope_spans=[
            ScopeSpans(
                scope=InstrumentationScope(name="opentelemetry-python", version="1.20.0"),
                spans=[auth_span],
            )
        ],
    )

    # Cart service resource spans (ERROR)
    cart_rs = ResourceSpans(
        resource=make_resource("cart-service", "1.2.0"),
        scope_spans=[
            ScopeSpans(
                scope=InstrumentationScope(name="opentelemetry-python", version="1.20.0"),
                spans=[cart_span],
            )
        ],
    )

    # Database resource spans
    db_rs = ResourceSpans(
        resource=make_resource("database", "14.5"),
        scope_spans=[
            ScopeSpans(
                scope=InstrumentationScope(name="opentelemetry-python", version="1.20.0"),
                spans=[db_span],
            )
        ],
    )

    request.resource_spans.extend([frontend_rs, auth_rs, cart_rs, db_rs])
    return request


def create_test_metrics() -> ExportMetricsServiceRequest:
    """
    Creates synthetic metrics showing:
    - Request counts
    - Error rates
    - Latency
    """
    now_nano = time.time_ns()

    request = ExportMetricsServiceRequest()

    # Cart service metrics (showing errors)
    cart_rm = ResourceMetrics(
        resource=make_resource("cart-service", "1.2.0"),
        scope_metrics=[
            ScopeMetrics(
                scope=InstrumentationScope(name="opentelemetry-python", version="1.20.0"),
                metrics=[
                    # Request count metric
                    Metric(
                        name="http.server.request.count",
                        description="Total HTTP requests",
                        unit="1",
                        sum=Sum(
                            aggregation_temporality=AggregationTemporality.AGGREGATION_TEMPORALITY_CUMULATIVE,
                            is_monotonic=True,
                            data_points=[
                                NumberDataPoint(
                                    time_unix_nano=now_nano,
                                    start_time_unix_nano=now_nano - 60_000_000_000,  # 60s ago
                                    as_int=100,  # 100 total requests
                                    attributes=[],
                                )
                            ],
                        ),
                    ),
                    # Error count metric
                    Metric(
                        name="http.server.error.count",
                        description="Total HTTP errors",
                        unit="1",
                        sum=Sum(
                            aggregation_temporality=AggregationTemporality.AGGREGATION_TEMPORALITY_CUMULATIVE,
                            is_monotonic=True,
                            data_points=[
                                NumberDataPoint(
                                    time_unix_nano=now_nano,
                                    start_time_unix_nano=now_nano - 60_000_000_000,
                                    as_int=15,  # 15 errors (15% error rate!)
                                    attributes=[make_attribute("http.status_code", 500)],
                                )
                            ],
                        ),
                    ),
                    # Latency metric (high!)
                    Metric(
                        name="http.server.duration",
                        description="HTTP request duration",
                        unit="ms",
                        gauge=Gauge(
                            data_points=[
                                NumberDataPoint(
                                    time_unix_nano=now_nano,
                                    start_time_unix_nano=now_nano - 60_000_000_000,
                                    as_double=1500.0,  # 1500ms - very high!
                                    attributes=[make_attribute("http.route", "/cart/items")],
                                )
                            ]
                        ),
                    ),
                ],
            )
        ],
    )

    # Frontend metrics (healthy)
    frontend_rm = ResourceMetrics(
        resource=make_resource("frontend", "2.1.0"),
        scope_metrics=[
            ScopeMetrics(
                scope=InstrumentationScope(name="opentelemetry-python", version="1.20.0"),
                metrics=[
                    Metric(
                        name="http.server.request.count",
                        description="Total HTTP requests",
                        unit="1",
                        sum=Sum(
                            aggregation_temporality=AggregationTemporality.AGGREGATION_TEMPORALITY_CUMULATIVE,
                            is_monotonic=True,
                            data_points=[
                                NumberDataPoint(
                                    time_unix_nano=now_nano,
                                    start_time_unix_nano=now_nano - 60_000_000_000,
                                    as_int=200,  # 200 requests
                                    attributes=[],
                                )
                            ],
                        ),
                    ),
                    Metric(
                        name="http.server.duration",
                        description="HTTP request duration",
                        unit="ms",
                        gauge=Gauge(
                            data_points=[
                                NumberDataPoint(
                                    time_unix_nano=now_nano,
                                    start_time_unix_nano=now_nano - 60_000_000_000,
                                    as_double=150.0,  # 150ms - healthy
                                    attributes=[],
                                )
                            ]
                        ),
                    ),
                ],
            )
        ],
    )

    request.resource_metrics.extend([cart_rm, frontend_rm])
    return request


def create_test_logs() -> ExportLogsServiceRequest:
    """
    Creates synthetic logs showing error events.
    """
    now_nano = time.time_ns()
    trace_id = generate_trace_id()
    span_id = generate_span_id()

    request = ExportLogsServiceRequest()

    # Cart service error logs
    cart_rl = ResourceLogs(
        resource=make_resource("cart-service", "1.2.0"),
        scope_logs=[
            ScopeLogs(
                scope=InstrumentationScope(name="app.logger", version="1.0.0"),
                log_records=[
                    LogRecord(
                        time_unix_nano=now_nano,
                        observed_time_unix_nano=now_nano,
                        severity_number=SeverityNumber.SEVERITY_NUMBER_ERROR,
                        severity_text="ERROR",
                        body=AnyValue(string_value="Database connection timeout after 5000ms"),
                        trace_id=trace_id,
                        span_id=span_id,
                        attributes=[
                            make_attribute("exception.type", "TimeoutError"),
                            make_attribute("db.host", "postgres-primary.internal"),
                            make_attribute("db.operation", "SELECT"),
                        ],
                    ),
                    LogRecord(
                        time_unix_nano=now_nano + 1_000_000_000,  # 1s later
                        observed_time_unix_nano=now_nano + 1_000_000_000,
                        severity_number=SeverityNumber.SEVERITY_NUMBER_ERROR,
                        severity_text="ERROR",
                        body=AnyValue(string_value="Failed to fetch cart items for user_id=12345"),
                        trace_id=trace_id,
                        span_id=span_id,
                        attributes=[
                            make_attribute("user_id", "12345"),
                            make_attribute("cart_id", "cart-abc-123"),
                        ],
                    ),
                ],
            )
        ],
    )

    # Auth service info logs (healthy)
    auth_rl = ResourceLogs(
        resource=make_resource("auth-service", "1.5.2"),
        scope_logs=[
            ScopeLogs(
                scope=InstrumentationScope(name="app.logger", version="1.0.0"),
                log_records=[
                    LogRecord(
                        time_unix_nano=now_nano,
                        observed_time_unix_nano=now_nano,
                        severity_number=SeverityNumber.SEVERITY_NUMBER_INFO,
                        severity_text="INFO",
                        body=AnyValue(string_value="User authentication successful"),
                        attributes=[
                            make_attribute("user_id", "12345"),
                            make_attribute("auth_method", "oauth2"),
                        ],
                    ),
                ],
            )
        ],
    )

    request.resource_logs.extend([cart_rl, auth_rl])
    return request


def main():
    """Generate all test data and print summary."""
    print("=" * 60)
    print("GENERATING SYNTHETIC OTLP TEST DATA")
    print("=" * 60)

    # Generate traces
    traces_req = create_test_traces()
    print(f"\n✅ Created {len(traces_req.resource_spans)} resource spans")
    for rs in traces_req.resource_spans:
        service = next((a.value.string_value for a in rs.resource.attributes if a.key == "service.name"), "unknown")
        span_count = sum(len(ss.spans) for ss in rs.scope_spans)
        print(f"   - {service}: {span_count} span(s)")

    # Generate metrics
    metrics_req = create_test_metrics()
    print(f"\n✅ Created {len(metrics_req.resource_metrics)} resource metrics")
    for rm in metrics_req.resource_metrics:
        service = next((a.value.string_value for a in rm.resource.attributes if a.key == "service.name"), "unknown")
        metric_count = sum(len(sm.metrics) for sm in rm.scope_metrics)
        print(f"   - {service}: {metric_count} metric(s)")

    # Generate logs
    logs_req = create_test_logs()
    print(f"\n✅ Created {len(logs_req.resource_logs)} resource logs")
    for rl in logs_req.resource_logs:
        service = next((a.value.string_value for a in rl.resource.attributes if a.key == "service.name"), "unknown")
        log_count = sum(len(sl.log_records) for sl in rl.scope_logs)
        print(f"   - {service}: {log_count} log record(s)")

    print("\n" + "=" * 60)
    print("TEST DATA SUMMARY")
    print("=" * 60)
    print("Scenario: E-commerce checkout flow with cart service failure")
    print("\nServices:")
    print("  - frontend (v2.1.0) - healthy, handling checkout requests")
    print("  - auth-service (v1.5.2) - healthy, user authentication working")
    print("  - cart-service (v1.2.0) - ERROR! Database timeout causing failures")
    print("  - database (v14.5) - healthy when reached, but cart-service can't connect")
    print("\nKey Issues:")
    print("  🔴 cart-service: 15% error rate (15/100 requests)")
    print("  🔴 cart-service: High latency (1500ms)")
    print("  🔴 cart-service: ERROR logs showing database timeout")
    print("\nExpected RCA:")
    print("  Root Cause: cart-service database connection pool exhausted")
    print("  Impact: Frontend checkout failing for users")
    print("=" * 60)

    return traces_req, metrics_req, logs_req


if __name__ == "__main__":
    main()
