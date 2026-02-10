# GitHub PR Integration with Graph Analysis

This document explains how the GitHub PR ingester connects to the graph folder for context-enriched RCA analysis.

## Architecture Overview

```
┌─────────────────────┐
│  GitHub Webhooks    │
│  (PRs, Commits)     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────────────┐
│  RootScout/github_ingester.py       │
│  - Fetches PR/commit details        │
│  - Filters by service path          │
│  - Emits ChangeEvent objects        │
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│  FileAppendSink                     │
│  Writes: github_events.jsonl        │
│  Format: JSONL (1 event per line)   │
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│  graph/data_parser.py               │
│  - Reads JSONL file                 │
│  - Converts to envelope format      │
│  - Matches events to services       │
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│  graph/agent.py                     │
│  - Enriches context with GitHub data│
│  - Includes file patches in prompt  │
│  - Sends to LLM for analysis        │
└─────────────────────────────────────┘
```

## Setup Instructions

### 1. Configure Environment Variables

Copy [.env.example](.env.example) to `.env` and configure:

```bash
# Required for GitHub ingestion
GITHUB_TOKEN=ghp_your_token_here
WATCH_REPO_OWNER=your_username
WATCH_REPO_NAME=your_repo

# IMPORTANT: This is where GitHub events are saved
GITHUB_OUTPUT_PATH=./github_events.jsonl

# Optional: Filter to specific service paths
WATCH_PATH_PREFIX=services/backend
SERVICE_ID=backend

# Required for LLM analysis
GEMINI_API_KEY=your_gemini_key_here
```

### 2. Start the RootScout Ingestion Service

The ingestion service listens for GitHub webhooks and saves events to the JSONL file:

```bash
# From project root
python -m RootScout.main
```

This will:
- Start a FastAPI server on port 8000
- Listen for GitHub webhooks at `/webhooks/github`
- Backfill recent PRs on startup
- Write events to `GITHUB_OUTPUT_PATH`

### 3. Configure GitHub Webhooks (Optional)

To receive real-time PR updates, configure a webhook in your GitHub repository:

1. Go to: Settings → Webhooks → Add webhook
2. Payload URL: `http://your-server:8000/webhooks/github`
3. Content type: `application/json`
4. Secret: (set `GITHUB_WEBHOOK_SECRET` in .env)
5. Events: Select "Pull requests" and "Pushes"

### 4. Run RCA Analysis

The graph analysis automatically enriches context with GitHub data:

```bash
cd graph
python run_simulation.py
```

The agent will:
1. Build the service dependency graph
2. Retrieve context for the failing service
3. **Automatically enrich with GitHub PR/commit data** from `github_events.jsonl`
4. Include file patches and change metadata in the LLM prompt
5. Generate an RCA report with recommended fixes

## Data Flow Example

### GitHub Event (saved to JSONL):
```json
{
  "ingested_at": "2025-02-10T15:30:45.123456+00:00",
  "event_type": "pull_request",
  "repo_owner": "asthamohta",
  "repo_name": "CS224G-SRE",
  "service_id": "backend",
  "watch_path_prefix": "services/backend",
  "pr_number": 42,
  "title": "Fix timeout in auth service",
  "url": "https://github.com/asthamohta/CS224G-SRE/pull/42",
  "files": [
    {
      "filename": "services/backend/auth.py",
      "status": "modified",
      "additions": 15,
      "deletions": 3,
      "patch": "@@ -45,7 +45,19 @@\n..."
    }
  ]
}
```

### Enriched Envelope (passed to LLM):
```json
{
  "source": "github",
  "kind": "code_change",
  "timestamp": "2025-02-10T15:30:45.123456+00:00",
  "summary": "modified: services/backend/auth.py (+15/-3)",
  "payload": {
    "filename": "services/backend/auth.py",
    "status": "modified",
    "additions": 15,
    "deletions": 3,
    "patch": "@@ -45,7 +45,19 @@...",
    "_meta": {
      "event_type": "pull_request",
      "repo": "asthamohta/CS224G-SRE",
      "service_id": "backend",
      "pr_number": 42,
      "title": "Fix timeout in auth service",
      "url": "https://github.com/asthamohta/CS224G-SRE/pull/42"
    }
  }
}
```

## Programmatic Usage

You can also use the integration programmatically:

```python
from graph.graph_builder import GraphBuilder
from graph.context_retriever import ContextRetriever
from graph.agent import RCAAgent
from llm_integration.client import GeminiClient

# Initialize components
graph_builder = GraphBuilder()
retriever = ContextRetriever(graph_builder)

# Pass github_output_path to agent
agent = RCAAgent(
    client=GeminiClient(),
    github_output_path="./github_events.jsonl"
)

# Ingest traces/spans to build graph
graph_builder.ingest_trace_span(span_data)

# Analyze a failing service
context = retriever.get_context("backend-service")
analysis = agent.analyze(context)  # Automatically enriched with GitHub data

print(analysis["reasoning"])
print(analysis["recommended_action"])
```

## Configuration Options

### data_parser.py enrichment parameters:

```python
enrich_context_from_github_output_path(
    context_packet,
    github_output_path="./github_events.jsonl",  # Direct file path
    env_var="GITHUB_OUTPUT_PATH",                # Or use env var
    max_events_per_service=25,                   # Limit events per service
    lookback_hours=168,                          # Only last week (7 days)
    verbose=True                                 # Print status messages
)
```

### Filtering Options:

- **WATCH_PATH_PREFIX**: Only ingest changes in specific directories (e.g., `services/cart`)
- **SERVICE_ID**: Override service ID derivation
- **lookback_hours**: Control how far back to look for relevant changes

## Troubleshooting

### No GitHub events showing up in analysis:

1. Check if `GITHUB_OUTPUT_PATH` is set and file exists:
   ```bash
   echo $GITHUB_OUTPUT_PATH
   ls -lh ./github_events.jsonl
   ```

2. Check if RootScout ingestion service is running:
   ```bash
   curl http://localhost:8000/healthz
   ```

3. Verify events are being written:
   ```bash
   tail -f ./github_events.jsonl
   ```

4. Check service_id matching:
   - `ChangeEvent.service_id` must match node service name in graph
   - Use `SERVICE_ID` env var to override if needed

### Events too old:

By default, only events from the last 168 hours (1 week) are included. Adjust with:

```python
agent = RCAAgent(client=client, github_output_path=path)
# In agent.analyze(), lookback_hours can be customized in data_parser call
```

### File patches truncated:

Large patches are truncated to 1200 characters per file. Adjust in [agent.py:56](graph/agent.py#L56):

```python
max_patch_chars = 1200  # Increase if needed
```

## Next Steps

1. **Start collecting data**: Run RootScout ingestion service to populate `github_events.jsonl`
2. **Test with mock data**: Run `graph/run_simulation.py` to see the integration in action
3. **Configure for production**: Set up GitHub webhooks for real-time ingestion
4. **Customize filtering**: Use `WATCH_PATH_PREFIX` to focus on specific services

## Related Files

- [RootScout/github_ingester.py](RootScout/github_ingester.py) - GitHub API client and webhook handler
- [RootScout/main.py](RootScout/main.py) - FastAPI ingestion service
- [graph/data_parser.py](graph/data_parser.py) - JSONL to envelope conversion
- [graph/agent.py](graph/agent.py) - RCA agent with auto-enrichment
- [graph/run_simulation.py](graph/run_simulation.py) - Example usage
- [.env.example](.env.example) - Configuration template
