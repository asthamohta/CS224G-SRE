import networkx as nx
import json
import time

class GraphBuilder:
    def __init__(self):
        # The core graph storage (Directed Graph)
        self.graph = nx.DiGraph()

    def _ensure_node(self, service_name):
        """Helper to ensure a node exists with default rich structure."""
        if service_name not in self.graph:
            self.graph.add_node(
                service_name,
                status="unknown",
                metadata={},       # For owner, runbook links, etc.
                recent_events=[],  # List of dicts: {type, description, timestamp}
                active_alerts=[]
            )

    def ingest_trace_span(self, span_data):
        """
        Ingests a single OpenTelemetry Span.
        Logic: If Service A (Parent) calls Service B (Child), draw an edge.
        """
        # 1. Extract Service Names
        # In real OTel, this is often nested under 'resource' -> 'attributes'
        service_name = span_data.get("service_name")
        parent_service = span_data.get("parent_service")
        
        # 2. Extract Metadata (Latency, Errors)
        has_error = span_data.get("status") == "ERROR"
        latency = span_data.get("latency_ms", 0)

        # 3. Add/Update the Node (The Service itself)
        # We update the node to reflect its LATEST status
        self._ensure_node(service_name)
        
        # Update status only if it's currently unknown or we have a new error state
        # (In a real system, we'd have more complex state aggregation)
        current_status = self.graph.nodes[service_name].get("status")
        new_status = "error" if has_error else "ok"
        
        # Simple latch: if we see an error, mark as error. If ok, mark as ok.
        # (This is a simplification for the prototype)
        nx.set_node_attributes(self.graph, {service_name: {"status": new_status}})

        # 4. Add the Edge (Dependency)
        # Only if there is a parent (Root spans don't have parents)
        if parent_service:
            self._ensure_node(parent_service)
            self.graph.add_edge(parent_service, service_name, latency=latency)
            print(f"[Graph] Updated dependency: {parent_service} -> {service_name}")

    def ingest_deployment_event(self, deployment_data):
        """
        Ingests a 'Stream Diff' (GitHub Webhook).
        Logic: Tag a specific service node with the new Commit Hash and record event.
        """
        service = deployment_data.get("service")
        commit_hash = deployment_data.get("commit_sha")
        timestamp = deployment_data.get("timestamp", time.time())
        summary = deployment_data.get("summary", "Deployment received")
        
        # Ensure node exists (even if we haven't seen traces yet)
        self._ensure_node(service)
        
        # Update current version
        nx.set_node_attributes(self.graph, {service: {"version": commit_hash}})
        
        # Append to history
        node = self.graph.nodes[service]
        event = {
            "type": "deployment",
            "commit": commit_hash,
            "timestamp": timestamp,
            "summary": summary
        }
        node["recent_events"].append(event)
        
        print(f"[Graph] Tagged {service} with commit {commit_hash} and added event.")

    def get_downstream_dependencies(self, service_node):
        """
        Used by the 'Fault Isolation Module'.
        Finds all services that 'service_node' depends on (recursively).
        """
        if service_node not in self.graph:
            return []
        # Return all successors (children, grandchildren, etc.)
        return list(nx.bfs_tree(self.graph, service_node))
