# RootScout

RootScout is an AI on-call agent that diagnosis production incidents automatically. 

Check us out at : [rootscout](https://cs-224-g-sre-2-mr8b.vercel.app)

---

## Prerequisites

- Python 3.9+
- Gemini API key from [Google AI Studio](https://aistudio.google.com/) and/or Anthropic API key
- Set `SLACK_BOT_TOKEN=xoxb-...` in your `.env` file to post real Slack messages (optional — all demos work in dry-run mode without it)

## Install

```bash
git clone https://github.com/asthamohta/CS224G-SRE.git
cd CS224G-SRE
pip install -r requirements.txt
pip install -r requirements_eval.txt
pip install -e .        # installs the `rootscout` CLI
```

## Configure

```bash
cp .env.example .env
# Set GEMINI_API_KEY and/or ANTHROPIC_API_KEY in .env
```

---

## Run — analyze a real incident

Once installed, use the `rootscout analyze` CLI. You need three things:
**(1) telemetry**, **(2) the failing service + incident time**, and
**(3) the codebase(s)** that back those services.

### Argument reference

| Flag | Required | What to pass |
|---|---|---|
| `--telemetry` | yes | One or more OTel export files (`.pb` protobuf or `.json`) **or** directories containing them. Pass the raw OTLP traces / metrics / logs exported from your collector. Multiple paths allowed. |
| `--incident-time` | yes | ISO 8601 timestamp of the incident, e.g. `2026-04-15T18:30:00Z`. |
| `--failing-service` | yes | Name of the alerting service (must match a `service.name` that appears in the telemetry). |
| `--codebases` | no | One or more **local directory paths** *or* **GitHub URLs** (e.g. `https://github.com/org/repo`) to index for code-level context. Multiple paths/URLs can be passed. |
| `--window-hours` | no | Hours of telemetry to look back from `--incident-time` (default: 10). |
| `--provider` | no | `claude` (default), `gemini`, `openai`, or `mock`. |
| `--model` | no | Specific model override, e.g. `claude-opus-4-6`. |
| `--github-events` | no | Path to a GitHub events JSONL file for recent-change context. |
| `--slack-channel` | no | Slack channel to post the report to (needs `SLACK_BOT_TOKEN`). |
| `--output`, `-o` | no | Path to write the full JSON RCA report. |

### End-to-end example (Online Boutique)

This example uses the cascading-failure scenario baked into
`rootscout.demo_otel_data` (cartservice timeout bringing down checkout) and
the public [Online Boutique](https://github.com/GoogleCloudPlatform/microservices-demo)
repo as the codebase.

**Step 1 — clone a codebase to point `--codebases` at:**

```bash
git clone --depth 1 https://github.com/GoogleCloudPlatform/microservices-demo /tmp/microservices-demo
```

**Step 2 — generate OTel `.pb` telemetry files** (the CLI's file ingester
reads OTLP protobuf / JSON, not raw CSV):

```bash
mkdir -p /tmp/rootscout-telemetry
python - <<'PY'
from rootscout.demo_otel_data import (
    create_boutique_traces, create_boutique_metrics, create_boutique_logs,
)
for name, req in [
    ("traces",  create_boutique_traces()),
    ("metrics", create_boutique_metrics()),
    ("logs",    create_boutique_logs()),
]:
    open(f"/tmp/rootscout-telemetry/{name}.pb", "wb").write(req.SerializeToString())
PY
```

**Step 3 — run the analyzer:**

```bash
rootscout analyze \
  --telemetry       /tmp/rootscout-telemetry/ \
  --incident-time   2026-04-16T03:57:16Z \
  --failing-service cartservice \
  --codebases       /tmp/microservices-demo/src \
  --provider        claude \
  --output          /tmp/rootscout-report.json
```

> Note: the demo telemetry uses `time.time()` at generation, so the incident
> time must be within the lookback window (default 10h) of when you ran
> Step 2. If you regenerate telemetry later, either update `--incident-time`
> or substitute `"$(date -u +%Y-%m-%dT%H:%M:%SZ)"`.

### Minimal example (single trace file, single local codebase)

```bash
rootscout analyze \
  --telemetry       ./traces.pb \
  --incident-time   2026-04-15T18:30:00Z \
  --failing-service cartservice \
  --codebases       /tmp/microservices-demo/src
```

### Using a GitHub URL instead of a local path for `--codebases`

```bash
rootscout analyze \
  --telemetry       /tmp/rootscout-telemetry/ \
  --incident-time   2026-04-15T18:30:00Z \
  --failing-service cartservice \
  --codebases       https://github.com/GoogleCloudPlatform/microservices-demo
```

### No API key? Use mock mode

```bash
rootscout analyze --provider mock \
  --telemetry       /tmp/rootscout-telemetry/ \
  --incident-time   2026-04-16T03:57:16Z \
  --failing-service cartservice \
  --codebases       /tmp/microservices-demo/src
```

---

## Evaluation

Three evaluation tracks test whether the agent correctly identifies the root cause component and reason. Scoring follows the [OpenRCA](https://github.com/microsoft/OpenRCA) protocol: exact string match on component, cosine similarity ≥ 0.50 (all-MiniLM-L6-v2) on reason.

### Eval 1 — Synthetic benchmark

Ten hand-crafted scenarios with known topology and injected faults.

```bash
python eval/run_eval.py              # all 10 scenarios
python eval/run_eval.py --mock       # no API key needed
python eval/run_eval.py --difficulty easy
```

---

### Eval 2 — OpenRCA (real Bank telemetry)

27 incidents from the [OpenRCA Bank dataset](https://github.com/microsoft/OpenRCA) — a Java-based banking microservices system with 14 pods.

**Data setup:** Download the Bank dataset and place it at `Bank/` in the project root:

```
Bank/
  query.csv
  record.csv
  telemetry/
    2021_03_04/
      metric/metric_container.csv
      log/log_service.csv
    2021_03_06/ ...
```

```bash
python eval/run_openrca_eval.py              # 27 Bank incidents
python eval/run_openrca_eval.py --mock       # no API key needed
python eval/run_openrca_eval.py --n 5        # quick test with 5 incidents
python eval/run_openrca_eval.py --bank-dir /path/to/Bank
```

---

### Eval 3 — RCAEvals (RE3-OB code-level faults)

Code-level faults injected into the Online Boutique microservices system from the [RCAEval benchmark](https://github.com/phamquiluan/RCAEval). Each case includes metric time series, logs with stack traces, and a known injection time.

**Data setup:**

```bash
git clone https://github.com/phamquiluan/RCAEval /tmp/RCAEval
cd /tmp/RCAEval && pip install -e .
python main.py --download --dataset RE3-OB
cp -r data/RE3-OB <project_root>/data/RE3-OB
```

```bash
python eval/run_rcaeval_eval.py              # all RE3-OB cases
python eval/run_rcaeval_eval.py --mock       # no API key needed
python eval/run_rcaeval_eval.py --n 5        # quick sanity check
python eval/run_rcaeval_eval.py --fault-types F1 F3
python eval/run_rcaeval_eval.py --model claude-opus
```

---

## Demo — End-to-End with Slack

Runs a full end-to-end scenario using RE3-OB telemetry: Slack alert fires → RootScout builds the causal graph → LLM identifies root cause → Slack RCA report is posted.

**Prerequisite:** RE3-OB data downloaded (see Eval 3 above).

```bash
# Dry-run (no Slack token needed):
python demo/demo_Rcaevals.py

# With real Slack:
SLACK_BOT_TOKEN=xoxb-... SLACK_ALERT_CHANNEL=#incidents python demo/demo_Rcaevals.py
```

---

## Results

| Dataset | Strengths | Limitations | Best Model | Component match | RCA cosine similarity |
|---|---|---|---|---|---|
| OpenRCA (Microsoft Bank) | Emulates real-life production incidents | Missing codebase | Claude Opus 4.6 | 45% | 18% |
| RCAEvals (RE3-OB) | Telemetry + codebase present; deeper code-level signals | Doesn't emulate real-life incidents well | Claude Opus 4.6 | 56% | 28% |
| Synthetic data | Easy to generate; controllable fault scenarios | Doesn't emulate real-life incidents | Claude Opus 4.6 | 100% | 91% |

---

## Known limitations

- **Datetime scoring on OpenRCA is not genuine.** The fault timestamp is taken directly from `record.csv` rather than predicted by the agent, so datetime criteria always pass.
- **No trace topology on real data.** `trace_span.csv` uses internal container IDs that don't map to pod names, so a static hand-written topology is used instead.
- **Noisy anomaly detection.** KPI thresholds are heuristic; during real incidents many pods spike simultaneously, making causal isolation harder.
- **Single system.** Only the Bank system is evaluated for OpenRCA. The dataset also includes Telecom and Market.
