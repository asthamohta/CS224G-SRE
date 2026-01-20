import json
from graph_builder import GraphBuilder

# 1. Initialize the Engine
engine = GraphBuilder()

# 2. Load the Mock Stream
print("--- STREAMING DATA START ---")
with open('test_data.json', 'r') as f:
    events = json.load(f)

for event in events:
    if event['type'] == 'span':
        engine.ingest_trace_span(event)
    elif event['type'] == 'diff':
        engine.ingest_deployment_event(event)
print("--- STREAMING FINISHED ---\n")

# 3. Simulate the "Fault Isolation" Query
# Scenario: Alert fires on 'frontend'. We need to see who is actually failing.
alerted_service = "frontend"
print(f"🚨 ALERT received on: {alerted_service}")
print("🔍 Querying Graph for dependencies...")

dependencies = engine.get_downstream_dependencies(alerted_service)
print(f"   Downstream Services: {dependencies}")

# 4. Find the Culprit (Simple Logic)
print("\n🕵️‍♀️ Fault Isolation Module Running...")
for service in dependencies:
    # Check the node's attributes in the graph
    node_data = engine.graph.nodes[service]
    status = node_data.get("status")
    version = node_data.get("version", "unknown")
    
    print(f"   Checking {service} (Version: {version})... Status: {status}")
    
    if status == "error":
        print(f"\n👉 ROOT CAUSE FOUND: {service}")
        print(f"   Suspicious Commit: {version}")
        print("   Action: Recommended rollback of this commit.")
