# Setting Up OpenTelemetry with RootScout

This guide shows you how to configure your applications to send OTLP (OpenTelemetry Protocol) data to RootScout for real-time RCA analysis.

## Prerequisites

- ✅ RootScout ingestion service running (`python -m RootScout.main`)
- ✅ `ENABLE_GRAPH_BUILDER=true` in your `.env` file
- ✅ Your application code

---

## Option 1: Python Auto-Instrumentation (Recommended) ⭐

**Best for:** Quick setup, automatic instrumentation of common frameworks (Flask, Django, FastAPI, requests, SQLAlchemy, etc.)

### Step 1: Install OpenTelemetry

```bash
# Install the distribution and OTLP exporter
pip install opentelemetry-distro opentelemetry-exporter-otlp

# Bootstrap auto-instrumentation (installs framework-specific packages)
opentelemetry-bootstrap -a install
```

This will automatically detect and install instrumentation for:
- Web frameworks (Flask, Django, FastAPI, Tornado)
- HTTP clients (requests, httpx, aiohttp)
- Databases (psycopg2, pymongo, redis, SQLAlchemy)
- And many more...

---

### Step 2: Configure Environment Variables

Create a `.env` file or export these variables:

```bash
# Required: Where to send OTLP data
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8000

# Required: Service identification
export OTEL_SERVICE_NAME=cart-service
export OTEL_SERVICE_VERSION=1.2.0

# Optional: Additional resource attributes
export OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=production

# Optional: Enable specific signals (default: all enabled)
export OTEL_TRACES_EXPORTER=otlp
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp

# Optional: Logging level
export OTEL_LOG_LEVEL=info
```

**Important Configuration Options:**

| Variable | Description | Example |
|----------|-------------|---------|
| `OTEL_SERVICE_NAME` | Service identifier (used for graph nodes) | `cart-service`, `frontend`, `auth-service` |
| `OTEL_SERVICE_VERSION` | Version tag (for deployment tracking) | `1.2.0`, `v2.3.1-beta` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | RootScout endpoint | `http://localhost:8000` |
| `OTEL_RESOURCE_ATTRIBUTES` | Comma-separated key=value pairs | `env=prod,region=us-west-2` |

---

### Step 3: Run Your Application

**Simple method:**
```bash
opentelemetry-instrument python your_app.py
```

**With environment file:**
```bash
# Load .env and run
source .env
opentelemetry-instrument python your_app.py
```

**Docker example:**
```dockerfile
FROM python:3.11

# Install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Install OpenTelemetry
RUN pip install opentelemetry-distro opentelemetry-exporter-otlp
RUN opentelemetry-bootstrap -a install

# Copy app
COPY . /app
WORKDIR /app

# Set environment variables
ENV OTEL_SERVICE_NAME=cart-service
ENV OTEL_SERVICE_VERSION=1.2.0
ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://rootscout:8000

# Run with auto-instrumentation
CMD ["opentelemetry-instrument", "python", "app.py"]
```

---

### Step 4: Verify It's Working

#### Check RootScout Logs

You should see incoming requests:
```
INFO:     127.0.0.1:54321 - "POST /v1/traces HTTP/1.1" 200 OK
INFO:     127.0.0.1:54322 - "POST /v1/metrics HTTP/1.1" 200 OK
INFO:     127.0.0.1:54323 - "POST /v1/logs HTTP/1.1" 200 OK
```

#### Query the Service Graph

```bash
curl http://localhost:8000/graph/status | jq
```

Response should show your service:
```json
{
  "node_count": 1,
  "nodes": [
    {
      "service": "cart-service",
      "status": "ok",
      "version": "v1.2.0",
      "dependencies": ["database"]
    }
  ]
}
```

#### Test with Traffic

```bash
# Make some requests to your app
curl http://localhost:5000/cart/items
curl http://localhost:5000/cart/items
curl http://localhost:5000/cart/items

# Check updated graph
curl http://localhost:8000/graph/status | jq '.nodes[] | select(.service=="cart-service")'
```

---

## Example: Flask Application

### Project Structure
```
my-flask-app/
├── .env                 # Environment configuration
├── requirements.txt     # Python dependencies
└── app.py              # Your Flask app
```

### requirements.txt
```
flask==3.0.0
opentelemetry-distro
opentelemetry-exporter-otlp
opentelemetry-instrumentation-flask
```

### .env
```bash
OTEL_SERVICE_NAME=cart-service
OTEL_SERVICE_VERSION=1.2.0
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8000
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=production,team=ecommerce
```

### app.py
```python
from flask import Flask, jsonify
import logging

# No OpenTelemetry imports needed - auto-instrumentation handles it!
app = Flask(__name__)
logger = logging.getLogger(__name__)

@app.route("/cart/items")
def get_cart_items():
    """Get cart items - automatically instrumented"""
    logger.info("Fetching cart items")

    # This will automatically create a span and send metrics
    items = [{"id": 1, "name": "Widget"}]

    return jsonify({"items": items})

@app.route("/cart/add", methods=["POST"])
def add_to_cart():
    """Add item to cart - automatically instrumented"""
    logger.info("Adding item to cart")

    # Simulate work
    import time
    time.sleep(0.1)

    return jsonify({"success": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
```

### Running It

```bash
# Install dependencies
pip install -r requirements.txt

# Bootstrap auto-instrumentation
opentelemetry-bootstrap -a install

# Load environment and run
source .env
opentelemetry-instrument python app.py
```

### What Gets Automatically Instrumented

✅ **HTTP Requests:** Every Flask route becomes a trace span
✅ **HTTP Client Calls:** Any `requests.get()` calls are traced
✅ **Database Queries:** SQLAlchemy, psycopg2, pymongo queries
✅ **Logging:** Logs are correlated with traces
✅ **Metrics:** Request counts, latency, errors

---

## Advanced Configuration

### Custom Span Attributes

Even with auto-instrumentation, you can add custom attributes:

```python
from opentelemetry import trace

@app.route("/cart/checkout")
def checkout():
    # Get current span (created by auto-instrumentation)
    span = trace.get_current_span()

    # Add custom attributes
    span.set_attribute("user.id", "12345")
    span.set_attribute("cart.total", 99.99)
    span.set_attribute("payment.method", "credit_card")

    # Your business logic
    process_checkout()

    return jsonify({"success": True})
```

### Custom Metrics

Add custom metrics alongside auto-instrumentation:

```python
from opentelemetry import metrics

# Get meter (auto-instrumentation sets this up)
meter = metrics.get_meter(__name__)

# Create custom metrics
checkout_counter = meter.create_counter(
    "cart.checkout.count",
    description="Number of checkouts"
)

items_sold_counter = meter.create_counter(
    "cart.items_sold",
    description="Total items sold"
)

@app.route("/cart/checkout", methods=["POST"])
def checkout():
    # Increment custom metrics
    checkout_counter.add(1, {"payment_method": "credit_card"})
    items_sold_counter.add(3)

    return jsonify({"success": True})
```

### Sampling Configuration

Control which traces are sent:

```bash
# Send all traces (default)
export OTEL_TRACES_SAMPLER=always_on

# Send no traces (disable)
export OTEL_TRACES_SAMPLER=always_off

# Sample 10% of traces
export OTEL_TRACES_SAMPLER=traceidratio
export OTEL_TRACES_SAMPLER_ARG=0.1

# Sample based on parent span
export OTEL_TRACES_SAMPLER=parentbased_always_on
```

### Filtering Sensitive Data

Exclude sensitive endpoints:

```python
# Create .otel-config.py
from opentelemetry.instrumentation.flask import FlaskInstrumentor

# Exclude specific URLs
FlaskInstrumentor().instrument_app(
    app,
    excluded_urls="/health,/metrics,/admin/password"
)
```

Or via environment:
```bash
export OTEL_PYTHON_FLASK_EXCLUDED_URLS="/health,/metrics,/admin/.*"
```

---

## Multiple Services Example

### Service 1: Frontend (Port 5000)

```bash
# .env
OTEL_SERVICE_NAME=frontend
OTEL_SERVICE_VERSION=2.1.0
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8000

# Run
opentelemetry-instrument python frontend.py
```

### Service 2: Cart Service (Port 5001)

```bash
# .env
OTEL_SERVICE_NAME=cart-service
OTEL_SERVICE_VERSION=1.2.0
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8000

# Run
opentelemetry-instrument python cart_service.py
```

### Service 3: Database Service (Port 5432)

Use database-specific instrumentation or OpenTelemetry Collector.

### Result

RootScout will automatically build this graph:
```
frontend → cart-service → database
```

---

## Troubleshooting

### No Data in RootScout

**Check 1: Is RootScout running?**
```bash
curl http://localhost:8000/healthz
# Should return: {"ok": true}
```

**Check 2: Is ENABLE_GRAPH_BUILDER enabled?**
```bash
# In .env
ENABLE_GRAPH_BUILDER=true
```

**Check 3: Are environment variables set?**
```bash
echo $OTEL_SERVICE_NAME
echo $OTEL_EXPORTER_OTLP_ENDPOINT
```

**Check 4: Is auto-instrumentation working?**
```bash
# Should see OpenTelemetry logs on startup
opentelemetry-instrument python app.py
# Look for: "Instrumenting <module> version X.Y.Z"
```

---

### Service Not Appearing in Graph

**Check service name:**
```bash
# Make sure OTEL_SERVICE_NAME is set and unique
export OTEL_SERVICE_NAME=cart-service  # NOT "cart_service" or "CartService"
```

**Generate traffic:**
```bash
# Make some requests to generate traces
curl http://localhost:5000/cart/items
```

**Verify endpoint:**
```bash
# Make sure endpoint is correct
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8000  # Not http://localhost:8000/v1/traces
```

---

### Dependencies Not Showing

**Make sure you're calling other services:**
```python
import requests

# This creates a client span that will link services
response = requests.get("http://cart-service:5001/items")
```

**Check for peer.service attribute:**

The instrumentation should automatically add this, but you can verify:
```python
from opentelemetry import trace

span = trace.get_current_span()
span.set_attribute("peer.service", "cart-service")
```

---

## Next Steps

1. ✅ **Instrument all your services** using the steps above
2. ✅ **Generate traffic** to populate the graph
3. ✅ **Verify the graph** via `/graph/status`
4. ✅ **Set up GitHub integration** (see [GITHUB_INTEGRATION.md](GITHUB_INTEGRATION.md))
5. ✅ **Configure alerting** to trigger RCA when issues occur
6. ✅ **Run RCA analysis** when alerts fire

---

## Related Documentation

- [OTLP_INTEGRATION.md](OTLP_INTEGRATION.md) - Complete OTLP integration guide
- [GITHUB_INTEGRATION.md](GITHUB_INTEGRATION.md) - GitHub webhook setup
- [QUICK_START.md](QUICK_START.md) - Quick start guide
- [DEMO_GUIDE.md](DEMO_GUIDE.md) - Demo walkthrough

---

## Support

For issues or questions:
- GitHub Issues: https://github.com/anthropics/claude-code/issues
- OpenTelemetry Docs: https://opentelemetry.io/docs/
- Python Auto-Instrumentation: https://opentelemetry.io/docs/languages/python/automatic/
