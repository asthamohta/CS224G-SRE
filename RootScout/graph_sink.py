"""
graph_sink.py
Connects OTel ingestion to the graph builder for real-time graph construction.
"""

import sys
import os
from typing import Any, Dict

# Add parent directory to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from RootScout.otel_ingester import TelemetrySink


class GraphBuilderSink(TelemetrySink):
    """
    Sink that transforms OTLP records into graph builder format and updates the graph.
    Handles traces (for dependencies), metrics (for health), and logs (for errors).
    """

    def __init__(self, graph_builder):
        """
        Args:
            graph_builder: Instance of graph.graph_builder.GraphBuilder
        """
        self.graph_builder = graph_builder
        self._service_health = {}  # Track service health from metrics/logs

    def emit(self, record: Dict[str, Any]) -> None:
        """
        Routes records by signal type to appropriate handlers.
        """
        signal = record.get("signal")

        if signal == "trace":
            self._handle_trace(record)
        elif signal == "metric":
            self._handle_metric(record)
        elif signal == "log":
            self._handle_log(record)

    def _handle_trace(self, record: Dict[str, Any]) -> None:
        """
        Convert OTLP trace record to graph builder span format and ingest.

        OTLP trace record format:
        {
            "service": "frontend",
            "trace_id": "...",
            "span_id": "...",
            "parent_span_id": "...",
            "name": "GET /api/cart",
            "status_code": 0,  # 0=UNSET, 1=OK, 2=ERROR
            "start_time_unix_nano": 1234567890000000000,
            "end_time_unix_nano": 1234567890100000000,
            "span_attributes": {...}
        }

        Graph builder expects:
        {
            "service_name": "frontend",
            "parent_service": "gateway",  # Extracted from context
            "status": "ERROR" | "OK",
            "latency_ms": 100
        }
        """
        service_name = record.get("service")
        if not service_name:
            return

        # Calculate latency
        start_nano = record.get("start_time_unix_nano", 0)
        end_nano = record.get("end_time_unix_nano", 0)
        latency_ms = (end_nano - start_nano) / 1_000_000 if end_nano > start_nano else 0

        # Determine status
        status_code = record.get("status_code", 0)
        status = "ERROR" if status_code == 2 else "OK"

        # Extract parent service from attributes
        # In real OTel, you might use span links, parent context, or conventions
        span_attrs = record.get("span_attributes", {})
        parent_service = self._extract_parent_service(record, span_attrs)

        # Build simplified span data
        span_data = {
            "service_name": service_name,
            "parent_service": parent_service,
            "status": status,
            "latency_ms": latency_ms,
            "span_name": record.get("name"),
            "trace_id": record.get("trace_id"),
            "span_id": record.get("span_id"),
        }

        # Ingest into graph
        self.graph_builder.ingest_trace_span(span_data)

    def _extract_parent_service(self, record: Dict[str, Any], span_attrs: Dict[str, Any]) -> str:
        """
        Extract parent service name from span attributes or context.

        Common patterns:
        - peer.service attribute
        - http.url or rpc.service attributes
        - Inferred from span name (e.g., "CallTo:auth-service")
        """
        # Check for explicit peer service attribute
        if "peer.service" in span_attrs:
            return span_attrs["peer.service"]

        # Check for HTTP target service
        if "http.target" in span_attrs:
            target = span_attrs["http.target"]
            # Extract service name from URL path (e.g., "/api/auth/..." -> "auth")
            parts = target.strip("/").split("/")
            if parts:
                return parts[0]

        # Check for RPC service
        if "rpc.service" in span_attrs:
            return span_attrs["rpc.service"]

        # Infer from span name (e.g., "GET /auth/...")
        span_name = record.get("name", "")
        if "/" in span_name:
            # Extract first path segment as potential service
            parts = span_name.split("/")
            for part in parts:
                if part and not part.startswith("api") and not part.startswith("v"):
                    return part

        # No parent found (root span)
        return None

    def _handle_metric(self, record: Dict[str, Any]) -> None:
        """
        Process metrics to track service health.

        Key metrics to watch:
        - Error rates (e.g., http.server.request.count with status=5xx)
        - Latency percentiles (e.g., http.server.duration p99)
        - Resource utilization (CPU, memory)
        """
        service_name = record.get("service")
        if not service_name:
            return

        metric_name = record.get("name", "")
        metric_type = record.get("type", "")
        points = record.get("points", [])

        if not service_name in self._service_health:
            self._service_health[service_name] = {
                "error_count": 0,
                "request_count": 0,
                "high_latency_count": 0,
            }

        # Track error metrics
        if "error" in metric_name.lower() or "5xx" in metric_name:
            for point in points:
                value = point.get("value", 0)
                self._service_health[service_name]["error_count"] += value

        # Track request metrics
        if "request" in metric_name.lower() or "rpc" in metric_name.lower():
            for point in points:
                value = point.get("value", 0)
                self._service_health[service_name]["request_count"] += value

        # Track latency (high latency = potential issue)
        if "latency" in metric_name.lower() or "duration" in metric_name.lower():
            for point in points:
                value = point.get("value", 0)
                # Flag high latency (>1000ms)
                if value > 1000:
                    self._service_health[service_name]["high_latency_count"] += 1

        # Update graph node health status based on metrics
        self._update_node_health_from_metrics(service_name)

    def _handle_log(self, record: Dict[str, Any]) -> None:
        """
        Process logs to detect errors and enrich context.

        Key patterns:
        - ERROR severity logs indicate service issues
        - Exception logs with stack traces
        - Logs correlated to traces (via trace_id)
        """
        service_name = record.get("service")
        if not service_name:
            return

        severity = record.get("severity_text", "")
        body = record.get("body", "")

        # Track errors from logs
        if severity in ["ERROR", "FATAL", "CRITICAL"]:
            if service_name not in self._service_health:
                self._service_health[service_name] = {
                    "error_count": 0,
                    "request_count": 0,
                    "high_latency_count": 0,
                }

            self._service_health[service_name]["error_count"] += 1

            # Update graph node with error event
            self.graph_builder._ensure_node(service_name)
            node = self.graph_builder.graph.nodes[service_name]

            error_event = {
                "type": "error_log",
                "severity": severity,
                "message": str(body)[:200],  # Truncate long messages
                "timestamp": record.get("time_unix_nano", 0) / 1_000_000_000,  # Convert to seconds
                "trace_id": record.get("trace_id"),
            }
            node["recent_events"].append(error_event)

            # Update node status to error if we see ERROR logs
            self._update_node_health_from_metrics(service_name)

    def _update_node_health_from_metrics(self, service_name: str) -> None:
        """
        Update graph node status based on accumulated metrics/logs.
        """
        if service_name not in self._service_health:
            return

        health = self._service_health[service_name]
        error_count = health.get("error_count", 0)
        request_count = health.get("request_count", 0)
        high_latency_count = health.get("high_latency_count", 0)

        # Determine status based on thresholds
        error_rate = error_count / request_count if request_count > 0 else 0

        # Mark as error if:
        # - Error rate > 5%
        # - Any errors without requests (error logs)
        # - High latency count > 10
        if error_rate > 0.05 or (error_count > 0 and request_count == 0) or high_latency_count > 10:
            status = "error"
        elif request_count > 0:
            status = "ok"
        else:
            status = "unknown"

        # Update graph node
        self.graph_builder._ensure_node(service_name)
        import networkx as nx
        nx.set_node_attributes(self.graph_builder.graph, {service_name: {"status": status}})

    def get_health_summary(self) -> Dict[str, Any]:
        """
        Returns a summary of tracked service health.
        Useful for debugging and monitoring the ingestion pipeline.
        """
        return dict(self._service_health)


class ComposedSink(TelemetrySink):
    """
    Sink that emits to multiple sinks (e.g., PrintSink + GraphBuilderSink).
    """

    def __init__(self, *sinks: TelemetrySink):
        self.sinks = list(sinks)

    def emit(self, record: Dict[str, Any]) -> None:
        for sink in self.sinks:
            try:
                sink.emit(record)
            except Exception as e:
                print(f"[ComposedSink] Error in sink {sink.__class__.__name__}: {e}")
