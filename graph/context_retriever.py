import networkx as nx
import json

class ContextRetriever:
    def __init__(self, graph_builder):
        self.graph_builder = graph_builder
        self.graph = graph_builder.graph

    def get_context(self, failing_service, lookback_seconds=3600):
        """
        Retrieves relevant context for a failing service.
        1. Identifies dependencies (who does this service call?).
        2. Filters for 'interesting' nodes:
           - Status == ERROR
           - Has recent events (deployments, etc.)
        3. Returns a structured 'Context Packet'.
        """
        if failing_service not in self.graph:
            return {"error": f"Service {failing_service} not found in graph."}

        # 1. Get dependencies (BFS)
        # We also include the failing service itself
        dependencies = list(nx.bfs_tree(self.graph, failing_service))
        
        context_packet = {
            "focus_service": failing_service,
            "related_nodes": []
        }

        # 2. Collect details for each node
        for node_name in dependencies:
            node_data = self.graph.nodes[node_name]
            
            # Check for recent events
            recent_events = node_data.get("recent_events", [])
            # (Optional) Filter events by lookback_seconds if we had real timestamps
            
            # Create a summary for this node
            node_summary = {
                "service": node_name,
                "status": node_data.get("status"),
                "version": node_data.get("version", "unknown"),
                "events": recent_events
            }
            
            context_packet["related_nodes"].append(node_summary)

        return context_packet

    def json_dump(self, context_packet):
        return json.dumps(context_packet, indent=2)
