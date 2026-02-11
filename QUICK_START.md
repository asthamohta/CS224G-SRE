# RootScout Quick Start

## Run the Demo (30 seconds)

```bash
python demo.py
```

That's it! The demo will:
1. Generate synthetic OTLP data (traces, metrics, logs)
2. Build a service dependency graph
3. Detect errors in cart-service
4. Enrich with GitHub PR data
5. Run AI-powered root cause analysis

## What You'll See

```
🚀 RootScout End-to-End Demo
────────────────────────────────────────────
Step 1: Initialize Components ✅
Step 2: Generate Synthetic OTLP Data ✅
Step 3: Ingest OTLP Data into Graph ✅
Step 4: Service Dependency Graph ✅
Step 5: Enrich with GitHub PR/Commit Data ✅
Step 6: Run Root Cause Analysis ✅
Step 7: RCA Analysis Results ✅

📋 INCIDENT REPORT
🎯 Root Cause Service: cart-service
📊 Confidence: 92%
💡 Analysis: Database connection pool exhausted...
🔧 Recommended Action: Merge PR #156
```

## Scenario

- **Problem:** E-commerce checkout failing (15% error rate)
- **Services:** frontend → auth-service ✅, cart-service 🔴, database ✅
- **Root Cause:** cart-service database timeout
- **Evidence:** OTLP metrics/logs + GitHub PR showing pool size fix

---