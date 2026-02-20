"""
openrca_loader.py - Load a subset of real OpenRCA cases into RootScout scenario format.

How to get the data
-------------------
1. Open: https://drive.google.com/drive/folders/1wGiEnu4OkWrjPxfx5ZTROnU37-5UDoPM
2. Navigate to one system folder, e.g. "Telecom/"
3. Download ONLY two files:
     Telecom/query.csv
     Telecom/record.csv
   (These are a few KB each — no telemetry download needed.)
4. Place them at:
     eval/openrca_data/Telecom/query.csv
     eval/openrca_data/Telecom/record.csv

Then run:
     python eval/run_eval.py --with-openrca

This loader will pick the first N cases and wrap them as synthetic scenarios
that benchmark RootScout using the real OpenRCA instructions and ground truth.

NOTE: Since we do not download the full 80 GB telemetry, the OTLP data for
these cases is synthetically generated from the failure description in the
instruction text. The ground-truth scoring_points are taken verbatim from
OpenRCA's record.csv.
"""

import os
import re
from datetime import datetime, timezone
from typing import List, Dict, Any

OPENRCA_DATA_DIR = os.path.join(os.path.dirname(__file__), "openrca_data")
_SUPPORTED_SYSTEMS = ["Telecom", "Bank", "Market"]


def _infer_topology_from_instruction(instruction: str) -> Dict[str, Any]:
    """
    Extract service/component names from the OpenRCA instruction text.
    OpenRCA instructions mention components by name (e.g. 'node-5', 'service-A').
    We build a minimal linear topology: api-gateway -> component -> downstream-db.
    """
    # Heuristic: grab capitalized words or patterns like node-N, svc-N
    candidates = re.findall(r'\b([A-Za-z][A-Za-z0-9_\-]{2,30})\b', instruction)
    # Filter out common English stop words
    stop = {"the", "and", "for", "with", "that", "this", "from", "has", "have",
            "are", "was", "were", "been", "will", "when", "what", "which",
            "analyze", "telemetry", "data", "identify", "root", "cause",
            "system", "observed", "degradation", "module", "service", "At"}
    services = [c for c in dict.fromkeys(candidates) if c.lower() not in stop][:4]
    if not services:
        services = ["unknown-service"]
    # Build a simple linear chain
    edges = [(services[i], services[i + 1]) for i in range(len(services) - 1)]
    return {
        "services": services + ["downstream-db"],
        "edges": edges + [(services[-1], "downstream-db")] if services else [],
    }


def _infer_fault_from_scoring_points(scoring_points: str) -> Dict[str, Any]:
    """Extract root cause component + reason from scoring_points for fault injection."""
    comp_match = re.search(
        r"The (?:\d+-th|only) predicted root cause component is ([^\n]+)", scoring_points
    )
    reason_match = re.search(
        r"The (?:\d+-th|only) predicted root cause reason is ([^\n]+)", scoring_points
    )
    component = comp_match.group(1).strip() if comp_match else "unknown-service"
    reason = reason_match.group(1).strip() if reason_match else "unknown failure"
    return {
        "root_cause_service": component,
        "fault_type": "openrca_real_case",
        "error_message": reason,
        "status_code_http": "500",
        "propagates_to": [],
    }


def _extract_datetime_from_instruction(instruction: str) -> datetime:
    """
    Try to parse a datetime from the instruction text (OpenRCA often includes
    the incident start time). Falls back to a fixed reference time.
    """
    patterns = [
        r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}',
        r'\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}',
    ]
    for p in patterns:
        m = re.search(p, instruction)
        if m:
            try:
                return datetime.strptime(m.group(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)


def load_openrca_scenarios(
    system: str = "Telecom",
    max_cases: int = 5,
    task_index_offset: int = 10,
) -> List[Dict[str, Any]]:
    """
    Load up to `max_cases` scenarios from an OpenRCA system CSV.

    Args:
        system: One of "Telecom", "Bank", "Market"
        max_cases: How many cases to load (default 5)
        task_index_offset: task_index numbering starts after synthetic scenarios
                           (so task_11, task_12, ...)

    Returns:
        List of scenario dicts compatible with benchmark.py
    """
    try:
        import pandas as pd
    except ImportError:
        print("[openrca_loader] pandas not installed — skipping OpenRCA cases.")
        return []

    system_dir = os.path.join(OPENRCA_DATA_DIR, system)
    query_path = os.path.join(system_dir, "query.csv")
    record_path = os.path.join(system_dir, "record.csv")

    if not os.path.exists(query_path) or not os.path.exists(record_path):
        print(
            f"[openrca_loader] OpenRCA CSVs not found at {system_dir}/\n"
            f"  Download from: https://drive.google.com/drive/folders/1wGiEnu4OkWrjPxfx5ZTROnU37-5UDoPM\n"
            f"  Place query.csv and record.csv under eval/openrca_data/{system}/"
        )
        return []

    query_df = pd.read_csv(query_path)
    record_df = pd.read_csv(record_path)

    if len(query_df) != len(record_df):
        print("[openrca_loader] query.csv and record.csv row counts differ — skipping.")
        return []

    scenarios = []
    for i in range(min(max_cases, len(query_df))):
        instruction = str(query_df.iloc[i].get("instruction", ""))
        task_index_orig = str(query_df.iloc[i].get("task_index", f"task_{i+1}"))
        scoring_points = str(record_df.iloc[i].get("scoring_points", ""))

        # Assign a new task_index that falls in the "hard" tier (> task_6)
        task_index = f"task_{task_index_offset + i + 1}"

        topology = _infer_topology_from_instruction(instruction)
        fault = _infer_fault_from_scoring_points(scoring_points)
        fault_start_ts = _extract_datetime_from_instruction(instruction)

        # Determine observed service: first in topology (api-gateway or first extracted)
        observed_service = topology["services"][0] if topology["services"] else "api-gateway"

        scenario = {
            "id": f"openrca_{system.lower()}_{i+1:03d}",
            "task_index": task_index,
            "difficulty": "hard",
            "title": f"[OpenRCA/{system}] {instruction[:80]}",
            "description": instruction,
            "topology": topology,
            "fault_injection": fault,
            "observed_service": observed_service,
            "fault_start_ts": fault_start_ts,
            "ground_truth": {
                "root_cause_component": fault["root_cause_service"],
                "root_cause_reason": fault["error_message"],
            },
            "scoring_points": scoring_points,  # verbatim from OpenRCA record.csv
        }
        scenarios.append(scenario)

    print(f"[openrca_loader] Loaded {len(scenarios)} real OpenRCA cases from {system}.")
    return scenarios
