# Connecting OpenTelemetry to RootScout

Quick guide for sending OTLP data (traces, metrics, logs) to RootScout for RCA analysis.

## Prerequisites

- RootScout running: `python -m RootScout.main`
- `.env` configured: `ENABLE_GRAPH_BUILDER=true`

## Setup (Python Auto-Instrumentation)

### 1. Install OpenTelemetry

```bash
pip install opentelemetry-distro opentelemetry-exporter-otlp
opentelemetry-bootstrap -a install
```

### 2. Configure Environment

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8000
export OTEL_SERVICE_NAME=your-service-name
export OTEL_SERVICE_VERSION=1.0.0
```

**Important:** `OTEL_SERVICE_NAME` is used as the service identifier in the dependency graph.

### 3. Run Your Application

```bash
opentelemetry-instrument python your_app.py
```

That's it! Your app will automatically send traces, metrics, and logs to RootScout.

## Verify It's Working

**Check RootScout logs:**
```bash
# Should see incoming OTLP requests
INFO: "POST /v1/traces HTTP/1.1" 200 OK
INFO: "POST /v1/metrics HTTP/1.1" 200 OK
INFO: "POST /v1/logs HTTP/1.1" 200 OK
```

**Query the service graph:**
```bash
curl http://localhost:8000/graph/status | jq
```

**Expected response:**
```json
{
  "node_count": 1,
  "nodes": [{
    "service": "your-service-name",
    "status": "ok",
    "dependencies": []
  }]
}
```

## What Gets Auto-Instrumented

✅ HTTP requests (Flask, Django, FastAPI)
✅ Database queries (SQLAlchemy, psycopg2, pymongo)
✅ HTTP client calls (requests, httpx)
✅ Logs (correlated with traces)
✅ Default metrics (request count, latency, errors)

## Custom Attributes (Optional)

Add business context to traces:

```python
from opentelemetry import trace

span = trace.get_current_span()
span.set_attribute("user.id", "12345")
span.set_attribute("cart.total", 99.99)
```

## Troubleshooting

**No data in RootScout?**
1. Check `ENABLE_GRAPH_BUILDER=true` in `.env`
2. Verify RootScout is running: `curl http://localhost:8000/healthz`
3. Check environment variables are set: `echo $OTEL_SERVICE_NAME`

**Service not in graph?**
- Generate traffic to your service (it needs activity to show up)
- Check `OTEL_SERVICE_NAME` is set correctly

---

## Related

- [GITHUB_INTEGRATION.md](GITHUB_INTEGRATION.md) - Correlate code changes with incidents
- [QUICK_START.md](QUICK_START.md) - Run the demo
