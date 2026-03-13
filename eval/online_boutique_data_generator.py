"""
online_boutique_data_generator.py - Richer OTLP + GitHub JSONL generator
for Online Boutique benchmark scenarios.

Differences from the base scenario_generator.py:
  - Adds realistic "noise" spans and logs at healthy services
  - Respects scenario["fault_injection"]["silent"] flag: root-cause service
    gets WARN-level logs (not ERROR spans) when silent=True, since it returns
    HTTP 200 with bad/degraded data rather than an outright failure
  - Injects scenario["noise_events"] into graph nodes so the LLM has to
    reason through plausible-but-irrelevant signals
  - Writes scenario["github_events"] to a NamedTemporaryFile (JSONL) and
    returns the path so benchmark.run_scenario() can pass it to RCAAgent

Public API
----------
    generate_ob_otlp(scenario) -> (traces, metrics, logs)
    write_github_events(scenario) -> str | None   (temp file path or None)
    generate_ob_data(scenario) -> (traces, metrics, logs, github_path)
"""

import json
import os
import tempfile
from collections import deque
from datetime import timezone
from typing import Any, Dict, List, Optional, Tuple

from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, InstrumentationScope, KeyValue
from opentelemetry.proto.logs.v1.logs_pb2 import LogRecord, ResourceLogs, ScopeLogs
from opentelemetry.proto.metrics.v1.metrics_pb2 import ResourceMetrics, ScopeMetrics
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span, Status

# ---------------------------------------------------------------------------
# Protobuf helpers (identical to scenario_generator.py for compatibility)
# ---------------------------------------------------------------------------

def _kv(key: str, value: str) -> KeyValue:
    return KeyValue(key=key, value=AnyValue(string_value=value))

def _kv_int(key: str, value: int) -> KeyValue:
    return KeyValue(key=key, value=AnyValue(int_value=value))

def _resource(service_name: str, version: str = "1.0.0") -> Resource:
    return Resource(attributes=[
        _kv("service.name", service_name),
        _kv("service.version", version),
        _kv("deployment.environment.name", "production"),
    ])

def _scope(service_name: str) -> InstrumentationScope:
    return InstrumentationScope(
        name=f"opentelemetry.instrumentation.{service_name}"
    )


# ---------------------------------------------------------------------------
# Span construction
# ---------------------------------------------------------------------------

def _make_span(
    service_name: str,
    span_name: str,
    trace_id: bytes,
    span_id: bytes,
    parent_span_id: Optional[bytes],
    start_ns: int,
    duration_ns: int,
    is_error: bool,
    error_message: str = "",
    http_status: str = "200",
) -> Span:
    status_code = Status.STATUS_CODE_ERROR if is_error else Status.STATUS_CODE_OK
    attrs = [
        _kv("http.method", "GET"),
        _kv("http.route", f"/{service_name}"),
        _kv("http.status_code", http_status),
    ]
    if is_error:
        attrs += [
            _kv("error", "true"),
            _kv("error.message", error_message[:200]),
        ]
    span = Span(
        trace_id=trace_id,
        span_id=span_id,
        name=span_name,
        kind=Span.SPAN_KIND_SERVER,
        start_time_unix_nano=start_ns,
        end_time_unix_nano=start_ns + duration_ns,
        status=Status(
            code=status_code,
            message=error_message[:200] if is_error else "",
        ),
        attributes=attrs,
    )
    if parent_span_id:
        span.parent_span_id = parent_span_id
    return span


# ---------------------------------------------------------------------------
# Trace generation
# ---------------------------------------------------------------------------

def generate_ob_traces(scenario: Dict[str, Any]) -> ExportTraceServiceRequest:
    """
    Generate a realistic trace for an OB scenario.

    Enhancements over the base generator:
    - Silent faults: root-cause span is STATUS_CODE_OK but has a slow duration
      and a 'degraded' attribute, making it harder to spot than an explicit error.
    - Noise spans: healthy services get short, successful spans so the graph
      is not trivially solved by "find the only error span".
    - Downstream propagation spans carry realistic gRPC/HTTP deadline messages.
    """
    topology = scenario["topology"]
    fault = scenario["fault_injection"]
    root_cause_svc = fault["root_cause_service"]
    propagates_to = set(fault.get("propagates_to", []))
    error_services = propagates_to | {root_cause_svc}
    silent = fault.get("silent", False)

    error_message = fault["error_message"]
    http_status = fault.get("status_code_http", "500")
    observed_service = scenario["observed_service"]

    fault_start_ts = scenario["fault_start_ts"]
    base_ns = int(fault_start_ts.replace(tzinfo=timezone.utc).timestamp() * 1e9)

    trace_id = bytes.fromhex("aabbccdd11223344aabbccdd11223344")
    services = topology["services"]
    edges = topology["edges"]

    # BFS from observed_service to assign parent pointers
    adj: Dict[str, List[str]] = {s: [] for s in services}
    for src, dst in edges:
        adj[src].append(dst)

    visited: Dict[str, Optional[str]] = {}
    queue: deque = deque([(observed_service, None)])
    order: List[str] = []
    while queue:
        svc, parent = queue.popleft()
        if svc in visited:
            continue
        visited[svc] = parent
        order.append(svc)
        for child in adj.get(svc, []):
            if child not in visited:
                queue.append((child, svc))

    # Assign span IDs
    span_ids: Dict[str, bytes] = {
        svc: bytes.fromhex(f"{(i + 1):016x}")
        for i, svc in enumerate(order)
    }

    resource_spans_list: List[ResourceSpans] = []

    for idx, svc in enumerate(order):
        parent_svc = visited[svc]
        parent_span_id = span_ids.get(parent_svc) if parent_svc else None
        start_offset = max(0, (len(order) - idx - 1)) * int(0.5e9)

        if svc == root_cause_svc:
            if silent:
                # Silent fault: OK status but very slow (signals degradation)
                span = _make_span(
                    service_name=svc,
                    span_name=f"GET /{svc}/handle",
                    trace_id=trace_id,
                    span_id=span_ids[svc],
                    parent_span_id=parent_span_id,
                    start_ns=base_ns + start_offset,
                    duration_ns=int(4.5e9),  # slow but not erroring
                    is_error=False,
                    http_status="200",
                )
                # Add a 'degraded' attribute to hint at the issue
                span.attributes.append(_kv("data.quality", "degraded"))
            else:
                span = _make_span(
                    service_name=svc,
                    span_name=f"GET /{svc}/handle",
                    trace_id=trace_id,
                    span_id=span_ids[svc],
                    parent_span_id=parent_span_id,
                    start_ns=base_ns + start_offset,
                    duration_ns=int(5e9),
                    is_error=True,
                    error_message=error_message,
                    http_status=http_status,
                )
        elif svc in propagates_to:
            # Downstream of root cause: deadline exceeded / upstream error
            upstream_msg = (
                f"RPC deadline exceeded waiting for {root_cause_svc} "
                f"after 10000ms - propagated error"
            )
            span = _make_span(
                service_name=svc,
                span_name=f"GET /{svc}/handle",
                trace_id=trace_id,
                span_id=span_ids[svc],
                parent_span_id=parent_span_id,
                start_ns=base_ns + start_offset,
                duration_ns=int(10e9),  # timeout duration
                is_error=True,
                error_message=upstream_msg,
                http_status=http_status,
            )
        else:
            # Healthy service: short successful span (noise)
            span = _make_span(
                service_name=svc,
                span_name=f"GET /{svc}/handle",
                trace_id=trace_id,
                span_id=span_ids[svc],
                parent_span_id=parent_span_id,
                start_ns=base_ns + start_offset,
                duration_ns=int(0.08e9),  # fast and healthy
                is_error=False,
                http_status="200",
            )

        rs = ResourceSpans(
            resource=_resource(svc),
            scope_spans=[ScopeSpans(scope=_scope(svc), spans=[span])],
        )
        resource_spans_list.append(rs)

    return ExportTraceServiceRequest(resource_spans=resource_spans_list)


# ---------------------------------------------------------------------------
# Log generation
# ---------------------------------------------------------------------------

_SEVERITY_ERROR = 17
_SEVERITY_WARN  = 13
_SEVERITY_INFO  = 9


def generate_ob_logs(scenario: Dict[str, Any]) -> ExportLogsServiceRequest:
    """
    Generate OTel logs for OB scenarios with noise and difficulty-appropriate
    severity levels.

    - Root-cause service:
        * silent=False → ERROR log (explicit fault)
        * silent=True  → WARN log (subtle, requires correlation with GitHub)
    - Propagated services: WARN with a realistic downstream message
    - No noise logs here; those are injected directly into graph nodes by
      wire_ob_graph() so the context retriever picks them up.
    """
    fault = scenario["fault_injection"]
    root_cause_svc = fault["root_cause_service"]
    propagates_to = fault.get("propagates_to", [])
    error_message = fault["error_message"]
    silent = fault.get("silent", False)

    fault_start_ts = scenario["fault_start_ts"]
    base_ns = int(fault_start_ts.replace(tzinfo=timezone.utc).timestamp() * 1e9)

    trace_id = bytes.fromhex("aabbccdd11223344aabbccdd11223344")
    resource_logs_list: List[ResourceLogs] = []

    # Root-cause log
    severity_num  = _SEVERITY_WARN if silent else _SEVERITY_ERROR
    severity_text = "WARN" if silent else "ERROR"

    root_log = LogRecord(
        time_unix_nano=base_ns + int(1e9),
        severity_number=severity_num,
        severity_text=severity_text,
        body=AnyValue(string_value=error_message),
        attributes=[
            _kv("log.logger", f"{root_cause_svc}.handler"),
            _kv("error.type", fault["fault_type"]),
            _kv("fault.silent", str(silent)),
        ],
        trace_id=trace_id,
    )
    rl = ResourceLogs(
        resource=_resource(root_cause_svc),
        scope_logs=[ScopeLogs(scope=_scope(root_cause_svc), log_records=[root_log])],
    )
    resource_logs_list.append(rl)

    # Downstream propagation logs
    for downstream_svc in propagates_to:
        msg = (
            f"Upstream call to {root_cause_svc} failed or timed out - "
            f"returning error to caller (attempt 1 of 1)"
        )
        warn_log = LogRecord(
            time_unix_nano=base_ns + int(2e9),
            severity_number=_SEVERITY_WARN,
            severity_text="WARN",
            body=AnyValue(string_value=msg),
            attributes=[
                _kv("log.logger", f"{downstream_svc}.client"),
                _kv("upstream.service", root_cause_svc),
            ],
            trace_id=trace_id,
        )
        rl = ResourceLogs(
            resource=_resource(downstream_svc),
            scope_logs=[ScopeLogs(scope=_scope(downstream_svc), log_records=[warn_log])],
        )
        resource_logs_list.append(rl)

    return ExportLogsServiceRequest(resource_logs=resource_logs_list)


# ---------------------------------------------------------------------------
# Metrics generation (minimal stubs)
# ---------------------------------------------------------------------------

def generate_ob_metrics(scenario: Dict[str, Any]) -> ExportMetricsServiceRequest:
    services = scenario["topology"]["services"]
    resource_metrics_list = [
        ResourceMetrics(
            resource=_resource(svc),
            scope_metrics=[ScopeMetrics(scope=_scope(svc), metrics=[])],
        )
        for svc in services
    ]
    return ExportMetricsServiceRequest(resource_metrics=resource_metrics_list)


# ---------------------------------------------------------------------------
# GitHub JSONL writer
# ---------------------------------------------------------------------------

def write_github_events(scenario: Dict[str, Any]) -> Optional[str]:
    """
    Write scenario["github_events"] to a temporary JSONL file.

    Returns the file path, or None if the scenario has no github_events.
    Caller is responsible for deleting the temp file after use.
    """
    events = scenario.get("github_events")
    if not events:
        return None

    fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="ob_github_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_ob_otlp(
    scenario: Dict[str, Any],
) -> Tuple[ExportTraceServiceRequest, ExportMetricsServiceRequest, ExportLogsServiceRequest]:
    """Generate all three OTLP signal types for an OB scenario."""
    traces  = generate_ob_traces(scenario)
    metrics = generate_ob_metrics(scenario)
    logs    = generate_ob_logs(scenario)
    return traces, metrics, logs


def generate_ob_data(
    scenario: Dict[str, Any],
) -> Tuple[
    ExportTraceServiceRequest,
    ExportMetricsServiceRequest,
    ExportLogsServiceRequest,
    Optional[str],
]:
    """
    Generate all OTLP signals plus a GitHub JSONL temp file.

    Returns:
        (traces, metrics, logs, github_path)
        github_path is None if the scenario has no github_events.
    """
    traces, metrics, logs = generate_ob_otlp(scenario)
    github_path = write_github_events(scenario)
    return traces, metrics, logs, github_path
