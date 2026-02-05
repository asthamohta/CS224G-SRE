import json
import os
import sys

# Ensure imports work from the root directory
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from graph_builder import GraphBuilder
from context_retriever import ContextRetriever
from agent import RCAAgent
from llm_integration.client import GeminiClient, MockClient

# 1. Initialize Engine
engine = GraphBuilder()
retriever = ContextRetriever(engine)

print("\n--- LLM SETUP ---")
agent = None

# ✅ USE OPTION B: Gemini API (Developer Flow)
try:
    print("🔌 Connecting to Gemini API (2.5 Flash)...")
    real_client = GeminiClient() # Automatically pulls from .env
    agent = RCAAgent(client=real_client)
except Exception as e:
    print(f"⚠️ Gemini API Init Failed: {e}")
    agent = RCAAgent(client=MockClient())

#Option B: Gemini API (Free Tier)
if not agent:
    try:
        print(f"🔌 Connecting to Gemini API (Key: {api_key})...")
        real_client = GeminiClient(api_key=api_key)
        agent = RCAAgent(client=real_client)
    except Exception as e:
        print(f"⚠️ Gemini API Init Failed: {e}")

# Fallback
if not agent:
    print("⚠️ Using Mock Client (No LLM connected).")
    agent = RCAAgent(client=MockClient())


# 2. Load the Mock Stream
print("--- STREAMING DATA START ---")
script_dir = os.path.dirname(os.path.abspath(__file__))
data_path = os.path.join(script_dir, 'test_data.json')

with open(data_path, 'r') as f:
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
print("🔍 Retrieving Context Packet...")

# Use the new Context Retriever
context = retriever.get_context(alerted_service)
print("--- [DEBUG] CONTEXT PACKET SENT TO LLM ---")
print(retriever.json_dump(context))
print("------------------------------------------")

# 4. Agentic Investigation
analysis = agent.analyze(context)

print("\n📋 FINAL INCIDENT REPORT")
print(json.dumps(analysis, indent=2))

