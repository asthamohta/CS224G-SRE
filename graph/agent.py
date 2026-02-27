import json
from typing import Any, Dict, List
from llm_integration.client import MockClient
from graph.data_parser import enrich_context_from_github_output_path


class RCAAgent:
    def __init__(self, client=None, github_output_path=None):
        """
        Initializes the RootScout RCA Agent.

        Args:
            client: LLM client (defaults to MockClient for safety)
            github_output_path: Path to GitHub JSONL file for context enrichment.
                               If not provided, will use GITHUB_OUTPUT_PATH env var.
        """
        self.client = client or MockClient()
        self.github_output_path = github_output_path

    def analyze(self, context_packet: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generates a professional Root Cause Analysis (RCA) report.
        Automatically enriches context with GitHub PR/commit data if available.
        """
        # Enrich context using GitHub JSONL (from instance path or GITHUB_OUTPUT_PATH env var)
        context_packet = enrich_context_from_github_output_path(
            context_packet,
            github_output_path=self.github_output_path,
            env_var="GITHUB_OUTPUT_PATH",
            max_events_per_service=25,
            lookback_hours=168,
            verbose=True,
        )

        prompt = self._construct_prompt(context_packet)

        print("🤖 [Agent] Prompt constructed. Sending to LLM...")
        response_str = self.client.generate_content(prompt)

        try:
            cleaned = response_str.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(cleaned)
            return parsed
        except Exception as e:
            print(f"[Agent] JSON parse failed: {e}")
            print(f"[Agent] Raw response tail: ...{response_str[-200:]}")
            return {"raw_response": response_str, "error": f"Failed to parse JSON: {str(e)}"}

    def _construct_prompt(self, context: Dict[str, Any]) -> str:
        """
        Source-agnostic prompt builder.

        Expects node["events"] to contain envelope events:
          {source, kind, timestamp, summary, payload}
        """
        # Safeguards for prompt size
        max_events_per_node = 12
        max_patch_chars = 1200

        # Build suspect summary with causal direction context
        all_nodes = context.get("related_nodes", [])
        error_nodes = [n for n in all_nodes if n.get("status") == "error"]
        suspect_lines = []
        for n in error_nodes:
            svc = n.get("service", "?")
            callers = n.get("called_by") or []
            error_callers = [c["service"] for c in callers if c.get("status") == "error"]
            evt_count = len(n.get("events") or [])
            if not error_callers:
                causal_hint = "⚠️  NO upstream errors — likely ROOT CAUSE"
            else:
                causal_hint = f"called by error services: {', '.join(error_callers)} — may be SYMPTOMATIC"
            suspect_lines.append(f"  - {svc} ({evt_count} events) | {causal_hint}")
        suspect_summary = (
            "\n".join(suspect_lines) if suspect_lines
            else "  - (none detected — check all nodes)"
        )

        # Build per-service detail block
        service_lines: List[str] = []
        for node in all_nodes:
            status_emoji = "🔴" if node.get("status") == "error" else "🟢"
            callers = node.get("called_by") or []
            if callers:
                caller_str = ", ".join(
                    f"{c['service']}({'🔴' if c.get('status') == 'error' else '🟢'})"
                    for c in callers
                )
                caller_note = f" | called_by=[{caller_str}]"
            else:
                caller_note = " | called_by=[] (entry point or uncalled)"
            line = f"- Service: {node.get('service')} {status_emoji} [status={node.get('status', 'ok')}]{caller_note}"

            events = node.get("events") or []

            # Sort events chronologically so the LLM can reason about causality
            def _ts_key(e):
                ts = e.get("timestamp", "") or ""
                if not ts or ts == "unknown":
                    # Fall back to numeric timestamp (graph_sink stores Unix seconds)
                    return float(e.get("timestamp", 0) or 0) if isinstance(e.get("timestamp"), (int, float)) else 0.0
                from datetime import datetime as _dt
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        parsed = _dt.strptime(ts[:19], fmt[:len(ts[:19])])
                        return parsed.timestamp()
                    except Exception:
                        continue
                try:
                    return float(ts)
                except Exception:
                    return 0.0

            events_sorted = sorted(events, key=_ts_key)

            for e in events_sorted[:max_events_per_node]:
                # Support both envelope format {source,kind,summary} and
                # graph_sink format {type,severity,message}
                src = e.get("source") or e.get("type", "unknown")
                kind = e.get("kind") or e.get("severity", "event")
                ts = e.get("timestamp")
                summary = e.get("summary") or e.get("message", "")

                line += f"\n  - [{src}/{kind}] {summary}".rstrip()
                if ts and ts != "unknown":
                    line += f" at {ts}"

                payload = e.get("payload") or {}
                if isinstance(payload, dict):
                    # Metric details
                    if payload.get("peak_value") is not None:
                        avg = payload.get("avg_value", "?")
                        peak = payload.get("peak_value", "?")
                        line += f" (avg={avg}, peak={peak})"

                    # GitHub / code change details
                    if payload.get("filename"):
                        line += f"\n    filename: {payload.get('filename')}"
                    if payload.get("status") is not None and payload.get("filename"):
                        adds = int(payload.get("additions") or 0)
                        dels = int(payload.get("deletions") or 0)
                        line += f"\n    status: {payload.get('status')} (+{adds}/-{dels})"
                    if payload.get("sha"):
                        line += f"\n    sha: {payload.get('sha')}"

                    patch = payload.get("patch")
                    if patch:
                        snippet = patch[:max_patch_chars]
                        line += f"\n    patch:\n{snippet}"
                        if len(patch) > max_patch_chars:
                            line += "\n    [patch truncated]"

            service_lines.append(line)

        context_str = "\n".join(service_lines)

        return f"""
### SYSTEM ROLE
You are the Lead On-Call Site Reliability Engineer (SRE) for RootScout.
Your goal is to investigate outages in distributed systems and identify "Patient Zero" — the single service where the fault ORIGINATED, not where it was first observed.
You are analytical, data-driven, and focused on minimizing Mean Time to Recovery (MTTR).

### INCIDENT CONTEXT
An alert has fired on the focus service: **{context.get('focus_service')}**.
Services are listed below with 🔴 = error status, 🟢 = ok status.
Nodes are ranked by suspicion: error services with the most anomalous events appear first.
All timestamps are in UTC.

### SUSPECT SERVICES (status=error)
{suspect_summary}

### SERVICE DETAILS
{context_str}

### CAUSAL DIRECTION RULES (apply in order)

**RULE 1 — Shared-infra overload (highest priority check)**
If a service is shared infrastructure (Redis, MySQL, database, cache, message queue) AND it has
2 or more error callers, it is almost certainly being OVERWHELMED by those callers — it is
SYMPTOMATIC, not the root cause. Do NOT pick it as root cause in this situation.
The root cause is one of those callers that first started generating excess load.

**RULE 2 — Cascade direction**
In a call chain A → B → C where both A and B show errors:
- If B has only one error caller (A), the chain likely cascaded from C upward. Look deeper.
- The DEEPEST service in the chain with a specific internal error event is the root cause.
- An "internal error event" is: OOM, high CPU, disk full, config error, connection pool exhausted,
  packet loss, JVM heap exhaustion — NOT generic "connection refused" or "timeout to downstream".

**RULE 3 — Earliest timestamp tiebreaker**
Among remaining candidates, the service whose EARLIEST anomalous event occurred first is root cause.

### INVESTIGATION STEPS
1. Identify any shared infra (Redis, MySQL, cache, queue) with 2+ error callers → mark as symptomatic.
2. Look at the remaining error services. Which has the earliest timestamp on an internal error event?
3. Confirm: does the failure propagate FROM that service outward to explain the other error services?
4. Name the specific failure MECHANISM (e.g. "high CPU usage", "network packet loss", "JVM OOM heap",
   "connection pool exhausted", "disk I/O saturation").

### RESPONSE FORMAT
Return ONLY a valid JSON object — no markdown, no extra text:
{{
  "root_cause_service": "<exact service name from the list above>",
  "root_cause_datetime": "<YYYY-MM-DD HH:MM:SS — earliest timestamp when fault began, UTC>",
  "confidence": <float 0.0–1.0>,
  "reasoning": "<Start with a short phrase naming the exact failure mechanism (e.g. 'high CPU usage', 'JVM Out of Memory heap', 'network packet loss', 'connection pool exhausted', 'disk I/O saturation', 'invalid API key'). Then in 1-2 sentences explain which service shows this as an INTERNAL signal and why other error services (especially shared infra like Redis/MySQL with multiple error callers) are symptomatic not causal.>",
  "recommended_action": "<specific remediation command>"
}}
""".strip()
