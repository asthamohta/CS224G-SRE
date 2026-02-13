"""
Synthetic OTLP scenario with cascading service degradation.

Service topology:
  frontend, checkout-service, cart-service, redis-cart,
  paymentservice, emailservice

Request flow:
  - Clients request /checkout on the frontend
  - frontend invokes checkout-service
  - checkout-service fans out to cart, payment, and email services
  - cart-service queries redis-cart

Failure model (root cause):
  - redis-cart intermittently responds slowly or times out 
  - cart-service emits ERROR spans and logs when redis calls fail
  - checkout-service shows elevated latency and occasional errors
  - frontend remains mostly healthy but with increased response time
"""

import random
import time
from typing import Union

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Status


def create_test_traces() -> ExportTraceServiceRequest:
    return _create_traces()

def create_test_metrics() -> ExportMetricsServiceRequest:
    return ExportMetricsServiceRequest()

def create_test_logs() -> ExportLogsServiceRequest:
    return _create_logs()


NUM_TRACES = int(random.choice([20, 25, 30]))

# root-cause failure rate for redis-cart operations
REDIS_TIMEOUT_RATE = 0.25
REDIS_SLOW_RATE = 0.35

# latency baselines (ms)
LAT_FRONTEND = (30, 8)
LAT_FRONTEND_TO_CHECKOUT = (15, 5)
LAT_CHECKOUT = (25, 8)
LAT_CHECKOUT_TO_CART = (12, 4)
LAT_CHECKOUT_TO_PAYMENT = (18, 6)
LAT_CHECKOUT_TO_EMAIL = (10, 3)
LAT_CART = (20, 6)

LAT_CART_TO_REDIS_OK = (8, 3)
LAT_REDIS_OK = (12, 4)

# slow/timeout redis
LAT_CART_TO_REDIS_SLOW = (80, 20)
LAT_REDIS_SLOW = (2500, 600)
LAT_REDIS_TIMEOUT = (5000, 200)

# chance of upstream symptom escalation when redis times out
CHECKOUT_ERROR_GIVEN_REDIS_TIMEOUT = 0.10
FRONTEND_ERROR_GIVEN_CHECKOUT_ERROR = 0.20


# Small utilities

Scalar = Union[str, int, bool, float]

def kv(key: str, value: Scalar) -> KeyValue:
    """Create a KeyValue with a best-effort AnyValue type."""
    av = AnyValue()
    if isinstance(value, bool):
        av.bool_value = value
    elif isinstance(value, int):
        av.int_value = value
    elif isinstance(value, float):
        av.double_value = value
    else:
        av.string_value = str(value)
    return KeyValue(key=key, value=av)

def ms_to_ns(ms: float) -> int:
    return int(ms * 1_000_000)

def choose_latency_ms(mean_ms: float, jitter_ms: float) -> float:
    return max(1.0, random.gauss(mu=mean_ms, sigma=jitter_ms))

def maybe(p: float) -> bool:
    return random.random() < p

def status(code: int, msg: str = "") -> Status:
    # 0=UNSET, 1=OK, 2=ERROR
    return Status(code=code, message=msg)

def add_service_bucket(req: ExportTraceServiceRequest, service_name: str):
    rs = req.resource_spans.add()
    rs.resource.attributes.append(kv("service.name", service_name))
    return rs.scope_spans.add()

def trace_id() -> bytes:
    return random.randbytes(16)

def span_id() -> bytes:
    return random.randbytes(8)



# Traces

def _create_traces() -> ExportTraceServiceRequest:
    req = ExportTraceServiceRequest()

    ss_frontend = add_service_bucket(req, "frontend")
    ss_checkout = add_service_bucket(req, "checkout-service")
    ss_cart = add_service_bucket(req, "cart-service")
    ss_payment = add_service_bucket(req, "paymentservice")
    ss_email = add_service_bucket(req, "emailservice")
    ss_redis = add_service_bucket(req, "redis-cart")

    now = time.time_ns()

    for i in range(NUM_TRACES):
        tid = trace_id()

        # --- frontend SERVER root span ---
        sp_frontend = ss_frontend.spans.add()
        sp_frontend.trace_id = tid
        sp_frontend.span_id = span_id()
        sp_frontend.name = "HTTP GET /checkout"
        sp_frontend.kind = 2  # SERVER

        # --- frontend -> checkout CLIENT ---
        sp_fe_to_co = ss_frontend.spans.add()
        sp_fe_to_co.trace_id = tid
        sp_fe_to_co.span_id = span_id()
        sp_fe_to_co.parent_span_id = sp_frontend.span_id
        sp_fe_to_co.name = "grpc.checkoutservice/PlaceOrder"
        sp_fe_to_co.kind = 3  # CLIENT
        sp_fe_to_co.status.CopyFrom(status(1))

        # --- checkout SERVER ---
        sp_checkout = ss_checkout.spans.add()
        sp_checkout.trace_id = tid
        sp_checkout.span_id = span_id()
        sp_checkout.parent_span_id = sp_fe_to_co.span_id
        sp_checkout.name = "grpc.checkoutservice/PlaceOrder"
        sp_checkout.kind = 2  # SERVER

        # --- checkout -> cart CLIENT ---
        sp_co_to_cart = ss_checkout.spans.add()
        sp_co_to_cart.trace_id = tid
        sp_co_to_cart.span_id = span_id()
        sp_co_to_cart.parent_span_id = sp_checkout.span_id
        sp_co_to_cart.name = "grpc.cartservice/GetCart"
        sp_co_to_cart.kind = 3  # CLIENT
        sp_co_to_cart.status.CopyFrom(status(1))

        # --- cart SERVER ---
        sp_cart = ss_cart.spans.add()
        sp_cart.trace_id = tid
        sp_cart.span_id = span_id()
        sp_cart.parent_span_id = sp_co_to_cart.span_id
        sp_cart.name = "grpc.cartservice/GetCart"
        sp_cart.kind = 2  # SERVER

        # --- cart -> redis CLIENT ---
        sp_cart_to_redis = ss_cart.spans.add()
        sp_cart_to_redis.trace_id = tid
        sp_cart_to_redis.span_id = span_id()
        sp_cart_to_redis.parent_span_id = sp_cart.span_id
        sp_cart_to_redis.name = "redis.GET cart:{user}"
        sp_cart_to_redis.kind = 3  # CLIENT

        # --- redis SERVER ---
        sp_redis = ss_redis.spans.add()
        sp_redis.trace_id = tid
        sp_redis.span_id = span_id()
        sp_redis.parent_span_id = sp_cart_to_redis.span_id
        sp_redis.name = "redis.GET"
        sp_redis.kind = 2  # SERVER

        # --- checkout -> payment/email fanout ---
        sp_co_to_pay = ss_checkout.spans.add()
        sp_co_to_pay.trace_id = tid
        sp_co_to_pay.span_id = span_id()
        sp_co_to_pay.parent_span_id = sp_checkout.span_id
        sp_co_to_pay.name = "grpc.paymentservice/Charge"
        sp_co_to_pay.kind = 3  # CLIENT
        sp_co_to_pay.status.CopyFrom(status(1))

        sp_payment = ss_payment.spans.add()
        sp_payment.trace_id = tid
        sp_payment.span_id = span_id()
        sp_payment.parent_span_id = sp_co_to_pay.span_id
        sp_payment.name = "grpc.paymentservice/Charge"
        sp_payment.kind = 2  # SERVER
        sp_payment.status.CopyFrom(status(1))

        sp_co_to_email = ss_checkout.spans.add()
        sp_co_to_email.trace_id = tid
        sp_co_to_email.span_id = span_id()
        sp_co_to_email.parent_span_id = sp_checkout.span_id
        sp_co_to_email.name = "grpc.emailservice/SendOrderConfirmation"
        sp_co_to_email.kind = 3  # CLIENT
        sp_co_to_email.status.CopyFrom(status(1))

        sp_email = ss_email.spans.add()
        sp_email.trace_id = tid
        sp_email.span_id = span_id()
        sp_email.parent_span_id = sp_co_to_email.span_id
        sp_email.name = "grpc.emailservice/SendOrderConfirmation"
        sp_email.kind = 2  # SERVER
        sp_email.status.CopyFrom(status(1))

        # Decide redis behavior for this trace
        redis_timeout = maybe(REDIS_TIMEOUT_RATE)
        redis_slow = (not redis_timeout) and maybe(REDIS_SLOW_RATE)

        lat_frontend = choose_latency_ms(*LAT_FRONTEND)
        lat_fe_to_co = choose_latency_ms(*LAT_FRONTEND_TO_CHECKOUT)
        lat_checkout = choose_latency_ms(*LAT_CHECKOUT)
        lat_co_to_cart = choose_latency_ms(*LAT_CHECKOUT_TO_CART)
        lat_cart = choose_latency_ms(*LAT_CART)
        lat_co_to_pay = choose_latency_ms(*LAT_CHECKOUT_TO_PAYMENT)
        lat_co_to_email = choose_latency_ms(*LAT_CHECKOUT_TO_EMAIL)
        lat_payment = choose_latency_ms(25, 8)
        lat_email = choose_latency_ms(18, 6)

        # Redis timings & status
        if redis_timeout:
            lat_cart_to_redis = choose_latency_ms(*LAT_CART_TO_REDIS_SLOW)
            lat_redis = choose_latency_ms(*LAT_REDIS_TIMEOUT)

            sp_redis.status.CopyFrom(status(2, "Redis timeout"))
            sp_redis.attributes.append(kv("exception.message", "redis: i/o timeout"))

            sp_cart_to_redis.status.CopyFrom(status(2, "Redis timeout"))
            sp_cart.status.CopyFrom(status(2, "Downstream redis timeout"))

        elif redis_slow:
            lat_cart_to_redis = choose_latency_ms(*LAT_CART_TO_REDIS_SLOW)
            lat_redis = choose_latency_ms(*LAT_REDIS_SLOW)
            sp_redis.status.CopyFrom(status(1))
            sp_cart_to_redis.status.CopyFrom(status(1))
            sp_cart.status.CopyFrom(status(1))

        else:
            lat_cart_to_redis = choose_latency_ms(*LAT_CART_TO_REDIS_OK)
            lat_redis = choose_latency_ms(*LAT_REDIS_OK)
            sp_redis.status.CopyFrom(status(1))
            sp_cart_to_redis.status.CopyFrom(status(1))
            sp_cart.status.CopyFrom(status(1))

        # assign timings 
        t0 = now + ms_to_ns(i * 40)

        sp_frontend.start_time_unix_nano = t0
        sp_frontend.end_time_unix_nano = t0 + ms_to_ns(
            lat_frontend
            + lat_fe_to_co
            + lat_checkout
            + lat_co_to_cart
            + lat_cart
            + lat_cart_to_redis
            + lat_redis
        )

        sp_fe_to_co.start_time_unix_nano = t0 + ms_to_ns(2)
        sp_fe_to_co.end_time_unix_nano = sp_fe_to_co.start_time_unix_nano + ms_to_ns(lat_fe_to_co)

        sp_checkout.start_time_unix_nano = sp_fe_to_co.start_time_unix_nano + ms_to_ns(1)
        sp_checkout.end_time_unix_nano = sp_checkout.start_time_unix_nano + ms_to_ns(
            lat_checkout + lat_co_to_cart + lat_cart + lat_cart_to_redis + lat_redis
        )

        sp_co_to_cart.start_time_unix_nano = sp_checkout.start_time_unix_nano + ms_to_ns(1)
        sp_co_to_cart.end_time_unix_nano = sp_co_to_cart.start_time_unix_nano + ms_to_ns(lat_co_to_cart)

        sp_cart.start_time_unix_nano = sp_co_to_cart.start_time_unix_nano + ms_to_ns(1)
        sp_cart.end_time_unix_nano = sp_cart.start_time_unix_nano + ms_to_ns(lat_cart + lat_cart_to_redis + lat_redis)

        sp_cart_to_redis.start_time_unix_nano = sp_cart.start_time_unix_nano + ms_to_ns(1)
        sp_cart_to_redis.end_time_unix_nano = sp_cart_to_redis.start_time_unix_nano + ms_to_ns(lat_cart_to_redis)

        sp_redis.start_time_unix_nano = sp_cart_to_redis.start_time_unix_nano + ms_to_ns(1)
        sp_redis.end_time_unix_nano = sp_redis.start_time_unix_nano + ms_to_ns(lat_redis)

        sp_co_to_pay.start_time_unix_nano = sp_checkout.start_time_unix_nano + ms_to_ns(2)
        sp_co_to_pay.end_time_unix_nano = sp_co_to_pay.start_time_unix_nano + ms_to_ns(lat_co_to_pay)

        sp_payment.start_time_unix_nano = sp_co_to_pay.start_time_unix_nano + ms_to_ns(1)
        sp_payment.end_time_unix_nano = sp_payment.start_time_unix_nano + ms_to_ns(lat_payment)

        sp_co_to_email.start_time_unix_nano = sp_checkout.start_time_unix_nano + ms_to_ns(3)
        sp_co_to_email.end_time_unix_nano = sp_co_to_email.start_time_unix_nano + ms_to_ns(lat_co_to_email)

        sp_email.start_time_unix_nano = sp_co_to_email.start_time_unix_nano + ms_to_ns(1)
        sp_email.end_time_unix_nano = sp_email.start_time_unix_nano + ms_to_ns(lat_email)

        # status propagation upward 
        if redis_timeout and maybe(CHECKOUT_ERROR_GIVEN_REDIS_TIMEOUT):
            sp_checkout.status.CopyFrom(status(2, "Cart retrieval failed"))
            if maybe(FRONTEND_ERROR_GIVEN_CHECKOUT_ERROR):
                sp_frontend.status.CopyFrom(status(2, "Checkout failed"))
            else:
                sp_frontend.status.CopyFrom(status(1))
        else:
            sp_checkout.status.CopyFrom(status(1))
            sp_frontend.status.CopyFrom(status(1))

        sp_frontend.attributes.append(kv("http.method", "GET"))
        sp_frontend.attributes.append(kv("http.route", "/checkout"))
        sp_frontend.attributes.append(kv("http.status_code", 500 if sp_frontend.status.code == 2 else 200))

    return req


# Logs

def _create_logs() -> ExportLogsServiceRequest:
    """
    Emits error logs primarily from cart-service & redis-cart when redis times out.
    Also emits occasional WARN logs from checkout-service.
    """
    req = ExportLogsServiceRequest()
    now = time.time_ns()

    # cart-service logs
    rl_cart = req.resource_logs.add()
    rl_cart.resource.attributes.append(kv("service.name", "cart-service"))
    sl_cart = rl_cart.scope_logs.add()

    # checkout-service logs
    rl_checkout = req.resource_logs.add()
    rl_checkout.resource.attributes.append(kv("service.name", "checkout-service"))
    sl_checkout = rl_checkout.scope_logs.add()

    # redis-cart logs
    rl_redis = req.resource_logs.add()
    rl_redis.resource.attributes.append(kv("service.name", "redis-cart"))
    sl_redis = rl_redis.scope_logs.add()

    for i in range(NUM_TRACES):
        if maybe(REDIS_TIMEOUT_RATE):
            lr = sl_cart.log_records.add()
            lr.time_unix_nano = now + ms_to_ns(i * 40)
            lr.severity_text = "ERROR"
            lr.severity_number = 17
            lr.body.string_value = "redis i/o timeout fetching cart:{user}"
            lr.attributes.append(kv("error.type", "RedisTimeout"))
            lr.attributes.append(kv("exception.message", "redis: i/o timeout"))

            lr2 = sl_redis.log_records.add()
            lr2.time_unix_nano = now + ms_to_ns(i * 40) + ms_to_ns(3)
            lr2.severity_text = "ERROR"
            lr2.severity_number = 17
            lr2.body.string_value = "slow command: GET took > 5s"
            lr2.attributes.append(kv("redis.command", "GET"))

        elif maybe(0.20):
            lr3 = sl_checkout.log_records.add()
            lr3.time_unix_nano = now + ms_to_ns(i * 40) + ms_to_ns(5)
            lr3.severity_text = "WARN"
            lr3.severity_number = 13
            lr3.body.string_value = "PlaceOrder latency elevated; waiting on cart-service"
            lr3.attributes.append(kv("symptom", "high_latency"))

    return req
