# Testing Guide: RootScout Components

Quick guide to test each component and understand what it does.

---

## 🎯 Quick Start

Run these in order to understand the system:

```bash
# 1. See raw synthetic data
python show_synthetic_data.py

# 2. Test OTEL ingester
python test_otel_ingester.py

# 3. Test GitHub ingester
python test_github_ingester.py

# 4. Run full demo
python demo.py
```

---

## 📊 Component Overview

### 1. **Synthetic Data Generator** (`RootScout/test_otel_data.py`)

**What it does:**
- Generates realistic OpenTelemetry traces, metrics, and logs
- Creates a specific failure scenario: cart-service database timeout

**How it works:**
- Uses OTLP protobuf format (same as real OTEL collector)
- Creates 4 spans across 3 services (frontend, cart-service, auth-service)
- Generates 2 log records (WARN + ERROR from cart-service)
- Links logs to traces via trace_id

**Test it:**
```bash
python show_synthetic_data.py
```

**Output shows:**
- ✅ Trace spans with timing and status
- ✅ Log records with severity and correlation
- ✅ Explanation of static vs dynamic data

---

### 2. **OTEL Ingester** (`RootScout/otel_ingester.py`)

**What it does:**
- Parses OTLP protobuf messages (traces, metrics, logs)
- Extracts attributes (service.name, http.*, db.*, etc.)
- Maps status codes (OK, ERROR)
- Maintains trace correlation (trace_id, span_id)

**How it works:**
1. Receives `ExportTraceServiceRequest` (protobuf)
2. Iterates through `resource_spans → scope_spans → spans`
3. Extracts resource attributes (service.name, version, environment)
4. Converts span attributes to dict
5. Emits normalized records to sink

**Test it:**
```bash
python test_otel_ingester.py
```

**Output shows:**
- ✅ 4 spans parsed (frontend, auth, cart x2)
- ✅ 2 logs parsed (WARN + ERROR)
- ✅ Trace correlation (logs linked to spans)
- ✅ Status mapping (OK vs ERROR)

---

### 3. **GitHub Ingester** (`Ingester/data_ingester.py`)

**What it does:**
- Receives GitHub webhook events (push, pull_request)
- Fetches file changes from GitHub API
- Filters changes to watched path (e.g., `services/cart/`)
- Emits normalized ChangeEvents

**How it works:**
1. Webhook arrives at `/webhooks/github`
2. Signature verified (HMAC-SHA256)
3. Fetches commit/PR files from GitHub REST API
4. Filters files matching `WATCH_PATH_PREFIX`
5. Emits `ChangeEvent` with service_id, files, commit_sha

**Test it:**
```bash
python test_github_ingester.py
```

**Output shows:**
- ✅ Webhook payload parsing
- ✅ File path filtering (keeps `services/cart/*`, filters out others)
- ✅ Service ID derivation
- ⚠️ Note: Needs real GitHub token to fetch files

**Run webhook server:**
```bash
cd Ingester
python main.py  # Starts on port 8000
```

---

### 4. **Graph Builder** (`graph/graph_builder.py`)

**What it does:**
- Builds NetworkX directed graph of service dependencies
- Tracks service health status (ok, error, unknown)
- Stores recent events (logs, errors) per service

**How it works:**
1. Receives parsed OTLP records from ingester
2. Creates nodes for each service
3. Creates edges for service calls (parent → child)
4. Tags nodes with health status based on error count
5. Stores recent events in node attributes

**Used in:** `demo.py`

---

### 5. **Context Retriever** (`graph/context_retriever.py`)

**What it does:**
- Extracts relevant context for a failing service
- Gets upstream/downstream dependencies
- Collects recent events (logs, traces, GitHub changes)

**How it works:**
1. Takes service name (e.g., "cart-service")
2. Traverses graph to find related nodes (distance ≤ 2)
3. Collects recent events from each node
4. Packages into context packet for LLM

**Used in:** `demo.py` (before calling RCA agent)

---

### 6. **RCA Agent** (`graph/agent.py`)

**What it does:**
- Analyzes context using Gemini LLM (2.5 Flash)
- Identifies root cause service
- Provides reasoning and recommended action

**How it works:**
1. Receives context packet (services, events, GitHub changes)
2. Formats prompt with structured data
3. Calls Gemini API with JSON schema
4. Returns structured analysis:
   - `root_cause_service`: Name of failing service
   - `confidence`: 0.0-1.0
   - `reasoning`: Explanation
   - `recommended_action`: Fix suggestion

**Used in:** `demo.py` (final step)

---

## 🔄 Full Pipeline Flow

```
1. GitHub Webhook
   ↓
   [GitHub Ingester] → ChangeEvent
                          ↓
                     (stored for later)

2. OTEL Collector
   ↓
   [OTEL Ingester] → Structured Records
                          ↓
   [Graph Builder] → Service Dependency Graph
                          ↓
                     (nodes have events)

3. Alert Triggered
   ↓
   [Context Retriever] → Context Packet
                              ↓
   [RCA Agent (LLM)] → Root Cause Analysis
                              ↓
                     Incident Report
```

---

## 📋 Demo Output Breakdown

When you run `python demo.py`, you'll see:

### **Step 1: Initialize Components**
Shows what each component does (1-2 line descriptions)

### **Step 2: Generate Synthetic OTLP Data**
Shows:
- Number of spans/metrics/logs generated
- Sample trace span (with status and error)
- Sample log record (with severity)

### **Step 3: Ingest OTLP Data**
Shows:
- Graph building process (edges created)
- Health summary (which services are unhealthy)
- Graph enrichment with proper dependencies

### **Step 4: Service Dependency Graph**
Shows:
- ASCII visualization of service tree
- Health status (🟢 OK, 🔴 ERROR)
- Recent events per service

### **Step 5: GitHub Enrichment**
Shows:
- Recent PRs/commits for services
- Which files changed

### **Step 6: RCA Analysis**
Shows:
- Context packet sent to LLM
- Full incident report with root cause

---

## 🐛 Troubleshooting

### GitHub Ingester: "Bad credentials"
**Cause:** No GitHub token set or invalid token
**Fix:** Set `GITHUB_TOKEN` in `.env` file

### Demo: "Gemini API unavailable"
**Cause:** No API key or rate limit exceeded
**Fix:** Set `GEMINI_API_KEY` in `.env`, or demo falls back to MockClient

### Graph: Self-loops or missing edges
**Cause:** Trace data doesn't have proper parent-child relationships
**Fix:** Check span `parent_span_id` is set correctly in synthetic data

---

## 📊 Understanding the Output

### Synthetic Data Characteristics:

| Aspect | Behavior |
|--------|----------|
| **Timestamps** | ✅ Dynamic (uses current time) |
| **Trace IDs** | 🔒 Static (hardcoded for reproducibility) |
| **Service names** | 🔒 Static (frontend, cart-service, auth-service) |
| **Error messages** | 🔒 Static (same timeout error) |
| **Latencies** | 🔒 Static (5000ms timeout, 100ms auth) |

**Why static?**
- Reproducible testing
- Predictable RCA results
- Demo-friendly (tells a coherent story)

**Want dynamic?**
Modify `test_otel_data.py` to use `random.choice()` for errors, `random.uniform()` for latencies.

---

## 🎯 What Each Test Proves

| Test | Proves |
|------|--------|
| `show_synthetic_data.py` | Data generation works, output is realistic |
| `test_otel_ingester.py` | Protobuf parsing works, trace correlation works |
| `test_github_ingester.py` | Webhook parsing works, filtering logic works |
| `demo.py` | Full pipeline works end-to-end |

---

## 📚 Next Steps

1. **Add more scenarios** to `test_otel_data.py` (OOM, network timeout, etc.)
2. **Make data dynamic** using `random` module
3. **Connect real OTEL collector** instead of synthetic data
4. **Set up real GitHub webhooks** with ngrok
5. **Store events in database** (PostgreSQL, ClickHouse)
6. **Add metrics support** (currently minimal)

---

## 💡 Key Takeaways

- **GitHub Ingester**: Watches for code changes → filters by service path
- **OTEL Ingester**: Parses telemetry → extracts structured data
- **Graph Builder**: Builds dependency map → tracks health
- **Context Retriever**: Gets relevant info → packages for LLM
- **RCA Agent**: Analyzes context → identifies root cause

Each component is **modular** and can be tested independently!
