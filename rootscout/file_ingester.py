"""
file_ingester.py — Load OTel export files (protobuf or JSON) from disk.

Supports time-window filtering so only telemetry around an incident is ingested.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from google.protobuf import json_format

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)

from rootscout.otel_ingester import OTelIngester, TelemetrySink


# ---------------------------------------------------------------------------
# TimeWindowSink — filters records by timestamp
# ---------------------------------------------------------------------------

class TimeWindowSink(TelemetrySink):
    """Wraps another sink, dropping records outside a time window."""

    def __init__(self, inner: TelemetrySink, start: datetime, end: datetime):
        self.inner = inner
        self.start_ns = int(start.timestamp() * 1e9)
        self.end_ns = int(end.timestamp() * 1e9)
        self.accepted = 0
        self.rejected = 0

    def emit(self, record: Dict[str, Any]) -> None:
        ts_ns = self._extract_timestamp_ns(record)
        if ts_ns is None or self.start_ns <= ts_ns <= self.end_ns:
            self.inner.emit(record)
            self.accepted += 1
        else:
            self.rejected += 1

    @staticmethod
    def _extract_timestamp_ns(record: Dict[str, Any]) -> Optional[int]:
        for key in ("start_time_unix_nano", "time_unix_nano"):
            val = record.get(key)
            if val:
                return int(val)
        # For metrics, check inside points
        points = record.get("points")
        if points and len(points) > 0:
            val = points[0].get("time_unix_nano")
            if val:
                return int(val)
        return None


# ---------------------------------------------------------------------------
# FileIngester — reads OTel files from disk
# ---------------------------------------------------------------------------

_TRACE_JSON_KEYS = {"resourceSpans", "resource_spans"}
_METRIC_JSON_KEYS = {"resourceMetrics", "resource_metrics"}
_LOG_JSON_KEYS = {"resourceLogs", "resource_logs"}


class FileIngester:
    """
    Reads OTel export files from disk and feeds them into the ingestion pipeline.

    Supports:
    - Protobuf binary files (.pb, .bin, .proto)
    - OTLP JSON files (.json)
    - Automatic signal type detection (traces/metrics/logs)
    """

    def __init__(self, sink: TelemetrySink):
        self.ingester = OTelIngester(sink=sink)
        self.results: list = []

    def ingest_file(self, path: str) -> Dict[str, Any]:
        """Ingest a single OTel export file. Returns summary dict."""
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"OTel file not found: {path}")

        ext = Path(path).suffix.lower()
        if ext in (".pb", ".bin", ".proto"):
            result = self._ingest_protobuf(path)
        elif ext == ".json":
            result = self._ingest_json(path)
        else:
            # Try protobuf first, fall back to JSON
            try:
                result = self._ingest_protobuf(path)
            except Exception:
                result = self._ingest_json(path)

        self.results.append(result)
        return result

    def ingest_directory(self, dir_path: str) -> List[Dict[str, Any]]:
        """Ingest all OTel files in a directory."""
        results = []
        dir_path = os.path.abspath(dir_path)
        for root, _, files in os.walk(dir_path):
            for fname in sorted(files):
                ext = Path(fname).suffix.lower()
                if ext in (".pb", ".bin", ".proto", ".json"):
                    fpath = os.path.join(root, fname)
                    try:
                        r = self.ingest_file(fpath)
                        results.append(r)
                    except Exception as e:
                        results.append({"file": fpath, "error": str(e)})
        return results

    def _ingest_protobuf(self, path: str) -> Dict[str, Any]:
        """Try parsing as each OTLP signal type."""
        data = open(path, "rb").read()

        # Try traces
        try:
            req = ExportTraceServiceRequest()
            req.ParseFromString(data)
            if req.resource_spans:
                r = self.ingester.ingest_traces(req)
                return {"file": path, "signal": "traces", "count": r.count}
        except Exception:
            pass

        # Try metrics
        try:
            req = ExportMetricsServiceRequest()
            req.ParseFromString(data)
            if req.resource_metrics:
                r = self.ingester.ingest_metrics(req)
                return {"file": path, "signal": "metrics", "count": r.count}
        except Exception:
            pass

        # Try logs
        try:
            req = ExportLogsServiceRequest()
            req.ParseFromString(data)
            if req.resource_logs:
                r = self.ingester.ingest_logs(req)
                return {"file": path, "signal": "logs", "count": r.count}
        except Exception:
            pass

        raise ValueError(f"Could not parse {path} as any OTLP protobuf signal type")

    def _ingest_json(self, path: str) -> Dict[str, Any]:
        """Parse OTLP JSON export file."""
        with open(path) as f:
            obj = json.load(f)

        keys = set(obj.keys())

        if keys & _TRACE_JSON_KEYS:
            req = json_format.ParseDict(obj, ExportTraceServiceRequest())
            r = self.ingester.ingest_traces(req)
            return {"file": path, "signal": "traces", "count": r.count}

        if keys & _METRIC_JSON_KEYS:
            req = json_format.ParseDict(obj, ExportMetricsServiceRequest())
            r = self.ingester.ingest_metrics(req)
            return {"file": path, "signal": "metrics", "count": r.count}

        if keys & _LOG_JSON_KEYS:
            req = json_format.ParseDict(obj, ExportLogsServiceRequest())
            r = self.ingester.ingest_logs(req)
            return {"file": path, "signal": "logs", "count": r.count}

        raise ValueError(
            f"Could not detect signal type in {path}. "
            f"Expected keys like resourceSpans, resourceMetrics, or resourceLogs."
        )
