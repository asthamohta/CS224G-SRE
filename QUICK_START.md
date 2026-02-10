# RootScout Quick Start

## 🚀 Run the Demo (30 seconds)

```bash
python demo.py
```

That's it! This shows the complete end-to-end RCA pipeline.

---

## 📋 What You'll See

```
Step 1: Initialize Components ✅
Step 2: Generate Synthetic OTLP Data ✅
Step 3: Ingest OTLP Data into Graph ✅
Step 4: Service Dependency Graph ✅
Step 5: Enrich with GitHub PR/Commit Data ✅
Step 6: Run Root Cause Analysis ✅
Step 7: RCA Analysis Results ✅

🎯 Root Cause Service: cart-service
📊 Confidence: 92%

💡 Analysis:
   Database connection pool exhausted causing timeouts...

🔧 Recommended Action:
   Merge PR #156 (Increase database connection pool size)
```

---

## 🎯 Demo Scenario

**Problem:** E-commerce checkout failing (15% error rate)

**Services:**
- 🟢 frontend → calls auth + cart
- 🟢 auth-service → calls database
- 🔴 **cart-service** → database timeouts (ROOT CAUSE)
- 🟢 database → healthy when reachable

**Evidence:**
- Traces show cart-service errors
- Metrics show 15% error rate, 1500ms latency
- Logs show "Database connection timeout"
- GitHub shows recent PR to fix pool size

**Result:** RCA correctly identifies cart-service as root cause

---

## 🔧 Configuration

Optional: Use real LLM (better analysis)

```bash
# 1. Get API key from https://ai.google.dev/
# 2. Set in .env
echo "GEMINI_API_KEY=your_key_here" >> .env

# 3. Run demo
python demo.py
```

---

## 📚 Next Steps

### Run Full Test Suite
```bash
cd RootScout
python test_otel_integration.py
```

### Start Production Ingestion Service
```bash
# 1. Configure .env (copy from .env.example)
cp .env.example .env
# Edit .env with your settings

# 2. Start service
python -m RootScout.main

# 3. Service runs at http://localhost:8000
# Endpoints:
#   - POST /v1/traces   (OTLP traces)
#   - POST /v1/metrics  (OTLP metrics)
#   - POST /v1/logs     (OTLP logs)
#   - GET  /graph/status (graph state)
```

### Instrument Your Services
```bash
# Python auto-instrumentation
pip install opentelemetry-distro opentelemetry-exporter-otlp
opentelemetry-bootstrap -a install

export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8000
export OTEL_SERVICE_NAME=my-service

opentelemetry-instrument python your_app.py
```

---

## 📖 Documentation

- **[DEMO_GUIDE.md](DEMO_GUIDE.md)** - Detailed demo walkthrough and customization
- **[OTLP_INTEGRATION.md](OTLP_INTEGRATION.md)** - OpenTelemetry setup and configuration
- **[GITHUB_INTEGRATION.md](GITHUB_INTEGRATION.md)** - GitHub webhook integration
- **[.env.example](.env.example)** - Configuration template

---

## 🎬 Demo Tips

**For quick demo (10 seconds):**
```python
# Edit demo.py:
DEMO_CONFIG = {
    "pause_between_steps": 0,  # No pauses
    "show_graph_details": False,
}
```

**For detailed walkthrough (2 minutes):**
```python
DEMO_CONFIG = {
    "pause_between_steps": 2.0,  # 2 second pauses
    "show_graph_details": True,
    "show_raw_otlp": True,  # Show OTLP structures
}
```

---

## ❓ Troubleshooting

### Missing dependencies?
```bash
pip install opentelemetry-proto networkx python-dotenv httpx google-generativeai
```

### Gemini API error?
Demo automatically falls back to mock client (still works!)

### Want to customize scenario?
Edit `SYNTHETIC_GITHUB_EVENTS` in [demo.py](demo.py)

---

## ✨ Key Features Demonstrated

✅ **OTLP Ingestion** - Traces, metrics, and logs
✅ **Service Graph** - Auto-built from trace spans
✅ **Health Tracking** - From metrics and log analysis
✅ **GitHub Enrichment** - Correlates code changes
✅ **LLM Analysis** - Intelligent root cause detection
✅ **Actionable Output** - Specific remediation steps

---

## 🎯 Expected Results

After running `python demo.py`:

- ✅ Ingests 4 trace spans, 3 metrics, 2 log records
- ✅ Builds graph with 4 services, 3 dependencies
- ✅ Identifies cart-service as 🔴 error
- ✅ Confidence score > 70%
- ✅ Recommends database pool increase

**Total runtime:** ~30 seconds (or ~10s with LLM)

---

## 💡 Use Cases

1. **Development:** Understand service dependencies
2. **Testing:** Validate instrumentation before production
3. **Presentations:** Show RCA capabilities to stakeholders
4. **Training:** Teach team about observability and RCA
5. **Debugging:** Quick sanity check of the pipeline

---

## 🚀 Ready to Go!

Just run:
```bash
python demo.py
```

That's all you need! 🎉
