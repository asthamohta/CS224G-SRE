"""
demo_otel_data.py — Generate realistic OTLP data for the Online Boutique demo.

Simulates a cascading failure scenario:
  checkoutservice deploys a bad commit → cartservice starts timing out
  → frontend returns 500s to users.

Services modeled after https://github.com/GoogleCloudPlatform/microservices-demo
"""

from __future__ import annotations

import time
import random

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span, Status
from opentelemetry.proto.metrics.v1.metrics_pb2 import (
    ResourceMetrics, ScopeMetrics, Metric, Gauge, NumberDataPoint,
)
from opentelemetry.proto.logs.v1.logs_pb2 import ResourceLogs, ScopeLogs, LogRecord
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.common.v1.common_pb2 import KeyValue, AnyValue, InstrumentationScope


def _kv(key: str, value: str) -> KeyValue:
    return KeyValue(key=key, value=AnyValue(string_value=value))

def _kv_int(key: str, value: int) -> KeyValue:
    return KeyValue(key=key, value=AnyValue(int_value=value))

def _kv_double(key: str, value: float) -> KeyValue:
    return KeyValue(key=key, value=AnyValue(double_value=value))


def _resource(service: str, version: str = "v0.10.1") -> Resource:
    return Resource(attributes=[
        _kv("service.name", service),
        _kv("service.version", version),
        _kv("deployment.environment.name", "production"),
        _kv("k8s.namespace.name", "default"),
    ])


def _scope(name: str = "opentelemetry-demo") -> InstrumentationScope:
    return InstrumentationScope(name=name)


# ---------------------------------------------------------------------------
# Trace data — cascading failure scenario
# ---------------------------------------------------------------------------

def create_boutique_traces() -> ExportTraceServiceRequest:
    """
    Online Boutique cascading failure:
      User → frontend → checkoutservice → cartservice (TIMEOUT)
      User → frontend → productcatalogservice (OK)
      User → frontend → currencyservice (OK)
      cartservice → redis (TIMEOUT)

    Root cause: checkoutservice deployed v0.10.2 with a bug that sends
    oversized payloads to cartservice, exhausting its connection pool.
    """
    now_ns = int(time.time() * 1e9)

    trace_id_1 = random.randbytes(16)
    trace_id_2 = random.randbytes(16)
    trace_id_3 = random.randbytes(16)

    all_resource_spans = []

    # === Trace 1: Checkout flow (FAILING) ===
    fe_span_id = random.randbytes(8)
    checkout_span_id = random.randbytes(8)
    cart_span_id = random.randbytes(8)
    redis_span_id = random.randbytes(8)

    # frontend → GET /cart/checkout
    fe_span = Span(
        trace_id=trace_id_1, span_id=fe_span_id,
        name="GET /cart/checkout", kind=Span.SPAN_KIND_SERVER,
        start_time_unix_nano=now_ns - int(8e9),
        end_time_unix_nano=now_ns - int(2e9),
        status=Status(code=Status.STATUS_CODE_ERROR, message="upstream timeout"),
        attributes=[
            _kv("http.method", "GET"), _kv("http.route", "/cart/checkout"),
            _kv("http.status_code", "504"), _kv("user.id", "user-98321"),
        ],
    )
    all_resource_spans.append(ResourceSpans(
        resource=_resource("frontend"), scope_spans=[ScopeSpans(scope=_scope(), spans=[fe_span])],
    ))

    # checkoutservice → PlaceOrder
    checkout_span = Span(
        trace_id=trace_id_1, span_id=checkout_span_id, parent_span_id=fe_span_id,
        name="grpc.hipstershop.CheckoutService/PlaceOrder", kind=Span.SPAN_KIND_SERVER,
        start_time_unix_nano=now_ns - int(7.9e9),
        end_time_unix_nano=now_ns - int(2.1e9),
        status=Status(code=Status.STATUS_CODE_ERROR, message="deadline exceeded calling CartService"),
        attributes=[
            _kv("rpc.system", "grpc"), _kv("rpc.service", "hipstershop.CheckoutService"),
            _kv("rpc.method", "PlaceOrder"), _kv("rpc.grpc.status_code", "4"),
            _kv("error", "true"),
            _kv("error.message", "DEADLINE_EXCEEDED: timeout waiting for CartService.GetCart response"),
        ],
    )
    all_resource_spans.append(ResourceSpans(
        resource=_resource("checkoutservice", "v0.10.2"),
        scope_spans=[ScopeSpans(scope=_scope(), spans=[checkout_span])],
    ))

    # cartservice → GetCart (TIMEOUT)
    cart_span = Span(
        trace_id=trace_id_1, span_id=cart_span_id, parent_span_id=checkout_span_id,
        name="grpc.hipstershop.CartService/GetCart", kind=Span.SPAN_KIND_SERVER,
        start_time_unix_nano=now_ns - int(7.8e9),
        end_time_unix_nano=now_ns - int(2.2e9),
        status=Status(code=Status.STATUS_CODE_ERROR, message="redis connection pool exhausted"),
        attributes=[
            _kv("rpc.system", "grpc"), _kv("rpc.service", "hipstershop.CartService"),
            _kv("rpc.method", "GetCart"), _kv("rpc.grpc.status_code", "4"),
            _kv("error", "true"),
            _kv("error.type", "RedisConnectionPoolExhausted"),
            _kv("error.message", "All 50 connections in use, 234 requests queued, timeout after 5000ms"),
            _kv("peer.service", "redis-cart"),
        ],
    )
    all_resource_spans.append(ResourceSpans(
        resource=_resource("cartservice"),
        scope_spans=[ScopeSpans(scope=_scope(), spans=[cart_span])],
    ))

    # redis-cart → GET (TIMEOUT)
    redis_span = Span(
        trace_id=trace_id_1, span_id=redis_span_id, parent_span_id=cart_span_id,
        name="redis GET cart:user-98321", kind=Span.SPAN_KIND_CLIENT,
        start_time_unix_nano=now_ns - int(7.7e9),
        end_time_unix_nano=now_ns - int(2.3e9),
        status=Status(code=Status.STATUS_CODE_ERROR, message="connection timeout"),
        attributes=[
            _kv("db.system", "redis"), _kv("db.operation", "GET"),
            _kv("db.statement", "GET cart:user-98321"),
            _kv("net.peer.name", "redis-cart"), _kv("net.peer.port", "6379"),
            _kv("error", "true"), _kv("error.type", "TimeoutError"),
        ],
    )
    all_resource_spans.append(ResourceSpans(
        resource=_resource("cartservice"),
        scope_spans=[ScopeSpans(scope=_scope(), spans=[redis_span])],
    ))

    # === Trace 2: Another failing checkout (different user) ===
    fe2_id = random.randbytes(8)
    co2_id = random.randbytes(8)
    cart2_id = random.randbytes(8)

    fe2 = Span(
        trace_id=trace_id_2, span_id=fe2_id,
        name="POST /cart/checkout", kind=Span.SPAN_KIND_SERVER,
        start_time_unix_nano=now_ns - int(5e9),
        end_time_unix_nano=now_ns - int(0.5e9),
        status=Status(code=Status.STATUS_CODE_ERROR, message="upstream timeout"),
        attributes=[
            _kv("http.method", "POST"), _kv("http.route", "/cart/checkout"),
            _kv("http.status_code", "504"), _kv("user.id", "user-44107"),
        ],
    )
    all_resource_spans.append(ResourceSpans(
        resource=_resource("frontend"), scope_spans=[ScopeSpans(scope=_scope(), spans=[fe2])],
    ))

    co2 = Span(
        trace_id=trace_id_2, span_id=co2_id, parent_span_id=fe2_id,
        name="grpc.hipstershop.CheckoutService/PlaceOrder", kind=Span.SPAN_KIND_SERVER,
        start_time_unix_nano=now_ns - int(4.9e9),
        end_time_unix_nano=now_ns - int(0.6e9),
        status=Status(code=Status.STATUS_CODE_ERROR, message="deadline exceeded calling CartService"),
        attributes=[
            _kv("rpc.system", "grpc"), _kv("rpc.method", "PlaceOrder"),
            _kv("rpc.grpc.status_code", "4"), _kv("error", "true"),
            _kv("error.message", "DEADLINE_EXCEEDED: CartService.AddItem timeout"),
        ],
    )
    all_resource_spans.append(ResourceSpans(
        resource=_resource("checkoutservice", "v0.10.2"),
        scope_spans=[ScopeSpans(scope=_scope(), spans=[co2])],
    ))

    cart2 = Span(
        trace_id=trace_id_2, span_id=cart2_id, parent_span_id=co2_id,
        name="grpc.hipstershop.CartService/AddItem", kind=Span.SPAN_KIND_SERVER,
        start_time_unix_nano=now_ns - int(4.8e9),
        end_time_unix_nano=now_ns - int(0.7e9),
        status=Status(code=Status.STATUS_CODE_ERROR, message="redis connection pool exhausted"),
        attributes=[
            _kv("rpc.system", "grpc"), _kv("rpc.method", "AddItem"),
            _kv("error", "true"),
            _kv("error.type", "RedisConnectionPoolExhausted"),
            _kv("error.message", "All 50 connections in use, timeout after 5000ms"),
        ],
    )
    all_resource_spans.append(ResourceSpans(
        resource=_resource("cartservice"),
        scope_spans=[ScopeSpans(scope=_scope(), spans=[cart2])],
    ))

    # === Trace 3: Healthy product browsing (no checkout) ===
    fe3_id = random.randbytes(8)
    prod_id = random.randbytes(8)
    currency_id = random.randbytes(8)

    fe3 = Span(
        trace_id=trace_id_3, span_id=fe3_id,
        name="GET /product/OLJCESPC7Z", kind=Span.SPAN_KIND_SERVER,
        start_time_unix_nano=now_ns - int(3e9),
        end_time_unix_nano=now_ns - int(2.8e9),
        status=Status(code=Status.STATUS_CODE_OK),
        attributes=[
            _kv("http.method", "GET"), _kv("http.route", "/product/:id"),
            _kv("http.status_code", "200"),
        ],
    )
    all_resource_spans.append(ResourceSpans(
        resource=_resource("frontend"), scope_spans=[ScopeSpans(scope=_scope(), spans=[fe3])],
    ))

    prod = Span(
        trace_id=trace_id_3, span_id=prod_id, parent_span_id=fe3_id,
        name="grpc.hipstershop.ProductCatalogService/GetProduct", kind=Span.SPAN_KIND_SERVER,
        start_time_unix_nano=now_ns - int(2.95e9),
        end_time_unix_nano=now_ns - int(2.85e9),
        status=Status(code=Status.STATUS_CODE_OK),
        attributes=[
            _kv("rpc.system", "grpc"), _kv("rpc.method", "GetProduct"),
        ],
    )
    all_resource_spans.append(ResourceSpans(
        resource=_resource("productcatalogservice"),
        scope_spans=[ScopeSpans(scope=_scope(), spans=[prod])],
    ))

    curr = Span(
        trace_id=trace_id_3, span_id=currency_id, parent_span_id=fe3_id,
        name="grpc.hipstershop.CurrencyService/Convert", kind=Span.SPAN_KIND_SERVER,
        start_time_unix_nano=now_ns - int(2.9e9),
        end_time_unix_nano=now_ns - int(2.87e9),
        status=Status(code=Status.STATUS_CODE_OK),
        attributes=[
            _kv("rpc.system", "grpc"), _kv("rpc.method", "Convert"),
        ],
    )
    all_resource_spans.append(ResourceSpans(
        resource=_resource("currencyservice"),
        scope_spans=[ScopeSpans(scope=_scope(), spans=[curr])],
    ))

    return ExportTraceServiceRequest(resource_spans=all_resource_spans)


# ---------------------------------------------------------------------------
# Log data — error logs from cartservice and checkoutservice
# ---------------------------------------------------------------------------

def create_boutique_logs() -> ExportLogsServiceRequest:
    now_ns = int(time.time() * 1e9)

    all_resource_logs = []

    # cartservice error logs
    cart_logs = [
        LogRecord(
            time_unix_nano=now_ns - int(30e9),
            severity_number=13, severity_text="WARN",
            body=AnyValue(string_value="Redis connection pool at 45/50 capacity — approaching limit"),
            attributes=[_kv("component", "redis_pool"), _kv("pool.active", "45"), _kv("pool.max", "50")],
        ),
        LogRecord(
            time_unix_nano=now_ns - int(20e9),
            severity_number=17, severity_text="ERROR",
            body=AnyValue(string_value="RedisConnectionPoolExhausted: All 50 connections in use. "
                          "Incoming request rate 340 req/s exceeds pool drain rate. "
                          "Queued 234 requests, oldest waiting 4200ms."),
            attributes=[
                _kv("component", "redis_pool"),
                _kv("error.type", "RedisConnectionPoolExhausted"),
                _kv("pool.active", "50"), _kv("pool.max", "50"),
                _kv("pool.queued", "234"), _kv("pool.oldest_wait_ms", "4200"),
            ],
        ),
        LogRecord(
            time_unix_nano=now_ns - int(15e9),
            severity_number=17, severity_text="ERROR",
            body=AnyValue(string_value="GetCart failed for user user-98321: "
                          "context deadline exceeded (timeout=5s)"),
            attributes=[
                _kv("component", "cart_handler"), _kv("method", "GetCart"),
                _kv("user_id", "user-98321"), _kv("error.type", "DeadlineExceeded"),
            ],
        ),
        LogRecord(
            time_unix_nano=now_ns - int(10e9),
            severity_number=17, severity_text="ERROR",
            body=AnyValue(string_value="AddItem failed for user user-44107: "
                          "context deadline exceeded (timeout=5s). "
                          "Traceback: cartservice/handler.go:142 → cartservice/redis_store.go:87"),
            attributes=[
                _kv("component", "cart_handler"), _kv("method", "AddItem"),
                _kv("user_id", "user-44107"), _kv("error.type", "DeadlineExceeded"),
            ],
        ),
        LogRecord(
            time_unix_nano=now_ns - int(5e9),
            severity_number=21, severity_text="FATAL",
            body=AnyValue(string_value="CIRCUIT BREAKER OPEN: Redis connection pool failures exceeded "
                          "threshold (15 failures in 60s). All cart operations will return errors "
                          "for next 30s cooldown period."),
            attributes=[
                _kv("component", "circuit_breaker"),
                _kv("breaker.state", "open"),
                _kv("breaker.failures", "15"),
                _kv("breaker.threshold", "10"),
            ],
        ),
    ]
    all_resource_logs.append(ResourceLogs(
        resource=_resource("cartservice"),
        scope_logs=[ScopeLogs(scope=_scope(), log_records=cart_logs)],
    ))

    # checkoutservice error logs
    checkout_logs = [
        LogRecord(
            time_unix_nano=now_ns - int(18e9),
            severity_number=13, severity_text="WARN",
            body=AnyValue(string_value="CartService.GetCart latency elevated: p99=4200ms (threshold=1000ms)"),
            attributes=[_kv("component", "checkout_handler"), _kv("downstream", "cartservice")],
        ),
        LogRecord(
            time_unix_nano=now_ns - int(12e9),
            severity_number=17, severity_text="ERROR",
            body=AnyValue(string_value="PlaceOrder failed: DEADLINE_EXCEEDED calling CartService.GetCart. "
                          "This started after deploying v0.10.2 which increased cart payload size "
                          "from 2KB to 48KB per request."),
            attributes=[
                _kv("component", "checkout_handler"), _kv("method", "PlaceOrder"),
                _kv("error.type", "DeadlineExceeded"), _kv("version", "v0.10.2"),
            ],
        ),
    ]
    all_resource_logs.append(ResourceLogs(
        resource=_resource("checkoutservice", "v0.10.2"),
        scope_logs=[ScopeLogs(scope=_scope(), log_records=checkout_logs)],
    ))

    # frontend error logs
    fe_logs = [
        LogRecord(
            time_unix_nano=now_ns - int(8e9),
            severity_number=17, severity_text="ERROR",
            body=AnyValue(string_value="HTTP 504 on /cart/checkout — upstream checkoutservice did not respond within 6s"),
            attributes=[
                _kv("component", "frontend_handler"), _kv("route", "/cart/checkout"),
                _kv("http.status_code", "504"),
            ],
        ),
    ]
    all_resource_logs.append(ResourceLogs(
        resource=_resource("frontend"),
        scope_logs=[ScopeLogs(scope=_scope(), log_records=fe_logs)],
    ))

    return ExportLogsServiceRequest(resource_logs=all_resource_logs)


# ---------------------------------------------------------------------------
# Metric data — gauge snapshots
# ---------------------------------------------------------------------------

def create_boutique_metrics() -> ExportMetricsServiceRequest:
    now_ns = int(time.time() * 1e9)

    all_resource_metrics = []

    # cartservice — connection pool metrics
    cart_metrics = [
        Metric(
            name="redis.pool.active_connections",
            description="Number of active Redis connections",
            unit="connections",
            gauge=Gauge(data_points=[
                NumberDataPoint(
                    time_unix_nano=now_ns - int(10e9),
                    as_int=50,
                    attributes=[_kv("service.name", "cartservice")],
                ),
            ]),
        ),
        Metric(
            name="redis.pool.queued_requests",
            description="Number of requests waiting for a Redis connection",
            unit="requests",
            gauge=Gauge(data_points=[
                NumberDataPoint(
                    time_unix_nano=now_ns - int(10e9),
                    as_int=234,
                    attributes=[_kv("service.name", "cartservice")],
                ),
            ]),
        ),
        Metric(
            name="grpc.server.request.duration",
            description="gRPC server request duration",
            unit="ms",
            gauge=Gauge(data_points=[
                NumberDataPoint(
                    time_unix_nano=now_ns - int(10e9),
                    as_double=4200.0,
                    attributes=[
                        _kv("rpc.method", "GetCart"),
                        _kv("rpc.grpc.status_code", "4"),
                    ],
                ),
            ]),
        ),
    ]
    all_resource_metrics.append(ResourceMetrics(
        resource=_resource("cartservice"),
        scope_metrics=[ScopeMetrics(scope=_scope(), metrics=cart_metrics)],
    ))

    # frontend — error rate
    fe_metrics = [
        Metric(
            name="http.server.error_rate",
            description="HTTP 5xx error rate",
            unit="%",
            gauge=Gauge(data_points=[
                NumberDataPoint(
                    time_unix_nano=now_ns - int(10e9),
                    as_double=23.5,
                    attributes=[_kv("http.route", "/cart/checkout")],
                ),
            ]),
        ),
    ]
    all_resource_metrics.append(ResourceMetrics(
        resource=_resource("frontend"),
        scope_metrics=[ScopeMetrics(scope=_scope(), metrics=fe_metrics)],
    ))

    return ExportMetricsServiceRequest(resource_metrics=all_resource_metrics)


def write_demo_files(output_dir: str = "/tmp") -> dict:
    """Generate and write all demo OTel files. Returns dict of file paths."""
    import os

    traces = create_boutique_traces()
    logs = create_boutique_logs()
    metrics = create_boutique_metrics()

    paths = {}
    for name, req in [("traces", traces), ("logs", logs), ("metrics", metrics)]:
        path = os.path.join(output_dir, f"boutique_{name}.pb")
        with open(path, "wb") as f:
            f.write(req.SerializeToString())
        paths[name] = path
        print(f"  Wrote {name}: {os.path.getsize(path)} bytes → {path}")

    return paths


if __name__ == "__main__":
    print("Generating Online Boutique demo telemetry...")
    write_demo_files()
