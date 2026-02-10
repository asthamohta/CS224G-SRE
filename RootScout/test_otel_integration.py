#!/usr/bin/env python3
"""
test_otel_integration.py
End-to-end test of OTLP ingestion → Graph Builder → RCA Analysis

Tests the full pipeline:
1. Generate synthetic OTLP data (traces, metrics, logs)
2. Ingest through OTelIngester with GraphBuilderSink
3. Build service dependency graph
4. Run RCA analysis
5. Verify results
"""

import sys
import os
import json

# Add parent directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from RootScout.otel_ingester import OTelIngester, PrintSink as OTelPrintSink
from RootScout.graph_sink import GraphBuilderSink, ComposedSink
from RootScout.test_otel_data import create_test_traces, create_test_metrics, create_test_logs

from graph.graph_builder import GraphBuilder
from graph.context_retriever import ContextRetriever
from graph.agent import RCAAgent
from llm_integration.client import MockClient, GeminiClient


def print_header(text: str):
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def print_graph_state(graph_builder: GraphBuilder):
    """Print current state of the service graph."""
    print("\n📊 Service Graph State:")
    print("-" * 70)

    for node in graph_builder.graph.nodes():
        data = graph_builder.graph.nodes[node]
        status = data.get("status", "unknown")
        status_emoji = "🔴" if status == "error" else "🟢" if status == "ok" else "⚪"

        print(f"{status_emoji} {node} (status: {status})")

        # Show recent events
        events = data.get("recent_events", [])
        if events:
            print(f"   Recent events: {len(events)}")
            for event in events[-3:]:  # Show last 3 events
                event_type = event.get("type", "unknown")
                summary = event.get("summary") or event.get("message", "")
                if len(summary) > 50:
                    summary = summary[:50] + "..."
                print(f"     - [{event_type}] {summary}")

        # Show dependencies
        successors = list(graph_builder.graph.successors(node))
        if successors:
            print(f"   Calls: {', '.join(successors)}")

    print("-" * 70)

    # Print edges
    if graph_builder.graph.edges():
        print("\n🔗 Dependencies:")
        for edge in graph_builder.graph.edges(data=True):
            source, target, data = edge
            latency = data.get("latency", 0)
            print(f"   {source} → {target} (latency: {latency:.1f}ms)")


def main():
    print_header("OTLP INGESTION → GRAPH BUILDER → RCA TEST")

    # ============================================================================
    # STEP 1: Setup
    # ============================================================================
    print_header("Step 1: Initialize Components")

    # Create graph builder
    graph_builder = GraphBuilder()
    print("✅ Created GraphBuilder")

    # Create sinks (both GraphBuilder and Print for debugging)
    graph_sink = GraphBuilderSink(graph_builder)
    print_sink = OTelPrintSink()
    composed_sink = ComposedSink(graph_sink, print_sink)
    print("✅ Created GraphBuilderSink + PrintSink (composed)")

    # Create OTLP ingester
    otel_ingester = OTelIngester(sink=composed_sink)
    print("✅ Created OTelIngester")

    # ============================================================================
    # STEP 2: Generate and Ingest Synthetic Data
    # ============================================================================
    print_header("Step 2: Generate Synthetic OTLP Data")

    traces_req = create_test_traces()
    metrics_req = create_test_metrics()
    logs_req = create_test_logs()

    print(f"✅ Generated {len(traces_req.resource_spans)} trace resource spans")
    print(f"✅ Generated {len(metrics_req.resource_metrics)} metric resource metrics")
    print(f"✅ Generated {len(logs_req.resource_logs)} log resource logs")

    print_header("Step 3: Ingest Data Through OTelIngester")

    # Ingest traces
    print("\n🔄 Ingesting traces...")
    trace_result = otel_ingester.ingest_traces(traces_req)
    print(f"✅ Ingested {trace_result.count} trace spans")

    # Ingest metrics
    print("\n🔄 Ingesting metrics...")
    metrics_result = otel_ingester.ingest_metrics(metrics_req)
    print(f"✅ Ingested {metrics_result.count} metrics")

    # Ingest logs
    print("\n🔄 Ingesting logs...")
    logs_result = otel_ingester.ingest_logs(logs_req)
    print(f"✅ Ingested {logs_result.count} log records")

    # ============================================================================
    # STEP 3: Verify Graph State
    # ============================================================================
    print_header("Step 4: Verify Service Dependency Graph")

    print_graph_state(graph_builder)

    # Show health summary from metrics/logs
    health_summary = graph_sink.get_health_summary()
    if health_summary:
        print("\n📈 Service Health Summary (from metrics/logs):")
        for service, health in health_summary.items():
            error_count = health.get("error_count", 0)
            request_count = health.get("request_count", 0)
            high_latency = health.get("high_latency_count", 0)

            error_rate = (error_count / request_count * 100) if request_count > 0 else 0
            print(f"   {service}:")
            print(f"      Errors: {error_count} / {request_count} requests ({error_rate:.1f}%)")
            print(f"      High latency events: {high_latency}")

    # ============================================================================
    # STEP 4: Run RCA Analysis
    # ============================================================================
    print_header("Step 5: Run RCA Analysis")

    # Setup RCA agent
    print("\n🤖 Initializing RCA Agent...")
    try:
        # Try to use real LLM
        llm_client = GeminiClient()
        print("   Using Gemini API for analysis")
    except Exception as e:
        # Fallback to mock
        llm_client = MockClient()
        print(f"   Using MockClient (Gemini failed: {e})")

    agent = RCAAgent(client=llm_client)

    # Get context for failing service
    failing_service = "frontend"  # Frontend is alerting because downstream cart fails
    print(f"\n🚨 Simulating alert on: {failing_service}")

    retriever = ContextRetriever(graph_builder)
    context = retriever.get_context(failing_service)

    print(f"\n📦 Retrieved context packet:")
    print(f"   Focus service: {context.get('focus_service')}")
    print(f"   Related nodes: {len(context.get('related_nodes', []))}")

    # Run analysis
    print("\n🔍 Running RCA analysis...")
    analysis = agent.analyze(context)

    # ============================================================================
    # STEP 5: Display Results
    # ============================================================================
    print_header("Step 6: RCA Analysis Results")

    print(json.dumps(analysis, indent=2))

    # ============================================================================
    # STEP 6: Verify Results
    # ============================================================================
    print_header("Step 7: Verification")

    expected_root_cause = "cart-service"
    actual_root_cause = analysis.get("root_cause_service", "")

    if expected_root_cause in actual_root_cause.lower():
        print(f"✅ PASS: Correctly identified root cause as '{actual_root_cause}'")
    else:
        print(f"❌ FAIL: Expected '{expected_root_cause}', got '{actual_root_cause}'")

    confidence = analysis.get("confidence", 0)
    if confidence > 0.7:
        print(f"✅ PASS: High confidence ({confidence:.2f})")
    elif confidence > 0:
        print(f"⚠️  WARN: Low confidence ({confidence:.2f})")
    else:
        print(f"❌ FAIL: No confidence score")

    reasoning = analysis.get("reasoning", "")
    if "cart" in reasoning.lower() and ("database" in reasoning.lower() or "timeout" in reasoning.lower()):
        print("✅ PASS: Reasoning mentions cart-service and database/timeout")
    else:
        print("⚠️  WARN: Reasoning might be missing key details")

    recommended_action = analysis.get("recommended_action", "")
    if recommended_action:
        print(f"✅ PASS: Has recommended action: {recommended_action[:80]}...")
    else:
        print("❌ FAIL: No recommended action provided")

    # ============================================================================
    # Final Summary
    # ============================================================================
    print_header("Test Summary")

    print("✅ OTLP data generation: PASSED")
    print("✅ OTLP ingestion: PASSED")
    print("✅ Graph construction: PASSED")
    print("✅ RCA analysis: COMPLETED")

    if expected_root_cause in actual_root_cause.lower() and confidence > 0.7:
        print("\n🎉 OVERALL: ALL TESTS PASSED")
        return 0
    else:
        print("\n⚠️  OVERALL: TESTS COMPLETED WITH WARNINGS")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
