import networkx as nx
import json

class GraphBuilder:
    def __init__(self):
        # The core graph storage (Directed Graph)
        self.graph = nx.DiGraph()

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
        self.graph.add_node(service_name, status="error" if has_error else "ok")

        # 4. Add the Edge (Dependency)
        # Only if there is a parent (Root spans don't have parents)
        if parent_service:
            self.graph.add_edge(parent_service, service_name, latency=latency)
            print(f"[Graph] Updated dependency: {parent_service} -> {service_name}")

    def ingest_deployment_event(self, deployment_data):
        """
        Ingests a 'Stream Diff' (GitHub Webhook).
        Logic: Tag a specific service node with the new Commit Hash.
        """
        service = deployment_data.get("service")
        commit_hash = deployment_data.get("commit_sha")
        
        if service in self.graph.nodes:
            # Add 'version' attribute to the node
            nx.set_node_attributes(self.graph, {service: {"version": commit_hash}})
            print(f"[Graph] Tagged {service} with commit {commit_hash}")
        else:
            print(f"[Warning] Received deploy for unknown service: {service}")

    def get_downstream_dependencies(self, service_node):
        """
        Used by the 'Fault Isolation Module'.
        Finds all services that 'service_node' depends on (recursively).
        """
        if service_node not in self.graph:
            return []
        # Return all successors (children, grandchildren, etc.)
        return list(nx.bfs_tree(self.graph, service_node))
