import networkx as nx
import json
from datetime import datetime


def _parse_ts(ts) -> float:
    """Convert any timestamp representation to a Unix float for comparison."""
    if ts is None:
        return float("inf")
    if isinstance(ts, (int, float)):
        return float(ts)
    s = str(ts).strip()
    if not s or s == "unknown":
        return float("inf")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(s[:19], fmt[:len(s[:19])]).timestamp()
        except Exception:
            continue
    try:
        return float(s)
    except Exception:
        return float("inf")


# HTTP method pseudo-nodes added by the OTEL ingester (GET, POST, etc.)
# are not real services — exclude from caller analysis.
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


class ContextRetriever:
    def __init__(self, graph_builder):
        self.graph_builder = graph_builder
        self.graph = graph_builder.graph

    def get_context(self, failing_service, lookback_seconds=3600, max_depth=4):
        """
        Retrieves relevant context for a failing service.

        Key improvements for causality accuracy:
        1. Depth-limited BFS — avoids pulling in the entire graph.
        2. Filters HTTP pseudo-nodes (GET, POST…) from caller lists — they are
           not real services and would corrupt the causal direction analysis.
        3. Adds 'called_by' (real service predecessors + their status) so the
           LLM can distinguish root-cause nodes from symptomatic shared infra.
           Shared infra (Redis, MySQL) called by 2+ error services is almost
           always being overwhelmed, not the origin of the fault.
        4. Ranks nodes so those with the fewest error callers appear first —
           a service with errors but NO error callers is the most suspicious.
        5. Adds 'earliest_anomaly_ts' per node for temporal causality ordering.
        6. Drops nodes that are healthy and have no events (pure noise).
        """
        if failing_service not in self.graph:
            return {"error": f"Service {failing_service} not found in graph."}

        # 1. Depth-limited BFS
        bfs_tree = nx.bfs_tree(self.graph, failing_service, depth_limit=max_depth)
        reachable = set(bfs_tree.nodes())

        # 2. Collect details for each node
        nodes = []
        for node_name in reachable:
            node_data = self.graph.nodes[node_name]
            recent_events = node_data.get("recent_events", [])
            status = node_data.get("status", "ok")

            # Drop nodes that are healthy and have nothing interesting to say
            if status != "error" and not recent_events:
                continue

            # Who calls this node? Filter out HTTP method pseudo-nodes.
            predecessors = list(self.graph.predecessors(node_name))
            callers = []
            for pred in predecessors:
                if pred.strip().lower() in _HTTP_METHODS:
                    continue  # not a real service
                pred_status = self.graph.nodes[pred].get("status", "ok") if pred in self.graph else "ok"
                callers.append({"service": pred, "status": pred_status})

            n_error_callers = sum(1 for c in callers if c["status"] == "error")

            # Earliest anomaly timestamp for temporal ranking
            ts_vals = [_parse_ts(e.get("timestamp")) for e in recent_events]
            earliest = min(ts_vals) if ts_vals else float("inf")

            nodes.append({
                "service": node_name,
                "status": status,
                "version": node_data.get("version", "unknown"),
                "events": recent_events,
                "called_by": callers,
                # internal ranking keys (stripped before returning)
                "_is_error": status == "error",
                "_n_error_callers": n_error_callers,
                "_event_count": len(recent_events),
                "_earliest_ts": earliest,
            })

        # 3. Rank by causal likelihood:
        #    Tier 0: error, 0 error callers  → most likely root cause
        #    Tier 1: error, 1 error caller   → possible in a cascade (downstream is root)
        #    Tier 2: error, 2+ error callers → likely symptomatic shared infra
        #    Tier 3: healthy with events     → context only
        #    Within each tier: earlier first anomaly = higher priority
        def _rank_key(n):
            ec = n["_n_error_callers"]
            if not n["_is_error"]:
                tier = 3
            elif ec == 0:
                tier = 0
            elif ec == 1:
                tier = 1
            else:
                tier = 2  # 2+ error callers → probably being overwhelmed
            return (tier, ec, n["_earliest_ts"])

        nodes.sort(key=_rank_key)

        # Strip internal ranking keys before returning
        related_nodes = [
            {k: v for k, v in n.items() if not k.startswith("_")}
            for n in nodes
        ]

        return {
            "focus_service": failing_service,
            "related_nodes": related_nodes,
        }

    def json_dump(self, context_packet):
        return json.dumps(context_packet, indent=2)
