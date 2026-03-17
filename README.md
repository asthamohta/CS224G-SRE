# RootScout

RootScout is an agentic system for automated root cause analysis (RCA) in distributed systems. It ingests telemetry (OTel traces, metrics, logs) and GitHub PR data, builds a causal dependency graph, and uses an LLM to identify which service caused an incident and why.

## How it works

1. **Graph construction** — Trace spans and metrics are ingested and wired into a directed dependency graph. Each node tracks health status and recent events.
2. **Fault isolation** — When an alert fires, BFS traversal from the alerting service collects the subgraph of suspects.
3. **Codebase context** — When a stack trace is detected in logs, RootScout parses the filename and line number, fetches the actual source code from GitHub, and attaches it to the graph node. The LLM sees the exact faulty line, not just the error message.
4. **LLM reasoning** — A Claude (or Gemini) agent receives the full context packet — graph, telemetry events, stack traces, source code — and returns a structured root cause report.
5. **Slack notification** — The incident alert and RCA report are posted back to Slack automatically.

---

## Quick start — live demo

The demo runs the full pipeline end-to-end on real RCAEval telemetry, with Slack in and Slack out.

### Prerequisites

```bash
pip install -r requirements.txt
pip install -r requirements_eval.txt
```

### API keys

Copy `.env.example` to `.env` and fill in:

```bash
ANTHROPIC_API_KEY=sk-ant-...       # required — drives the RCA agent
SLACK_BOT_TOKEN=xoxb-...           # optional — posts to Slack
SLACK_ALERT_CHANNEL=#incidents     # optional — which channel to post to
```

### Download the RE3-OB dataset

```bash
python -c "
import sys; sys.path.insert(0, '/tmp/RCAEval')
# first clone: git clone https://github.com/phamquiluan/RCAEval /tmp/RCAEval
from RCAEval.utility import download_re3ob_dataset
download_re3ob_dataset('data/RE3')
"
```

This downloads ~200 MB into `data/RE3/RE3-OB/`.

### Run

```bash
python demo_rcaeval.py
```

Without `SLACK_BOT_TOKEN` the Slack messages are printed to the terminal in a formatted box. With it, they post to your configured channel.

### Demo flow (≈75 seconds)

| Step | What you see |
|---|---|
| 1 | Slack alert arrives — cartservice erroring, OverflowException, p99 +340ms |
| 2 | Telemetry loaded — metrics + logs for ±15 min window across all 12 services |
| 3 | BFS graph traversal — each service printed live as the agent visits it; stack trace shown line by line; source code fetched from GitHub |
| 4 | System prompt displayed — full context assembled for the LLM |
| 5 | Claude reasons — root cause, confidence, propagation explanation, fix command |
| 6 | RCA posted back to Slack |

---

## Evaluation

Three evaluation tracks measure whether the agent correctly identifies the component and reason for a fault, using [OpenRCA](https://github.com/microsoft/OpenRCA) scoring.

Install eval dependencies:

```bash
pip install -r requirements_eval.txt
```

### Scoring

Each incident is scored on up to three criteria depending on the task type:

| Criterion | Match method |
|---|---|
| Root cause component | Exact string match |
| Root cause reason | Cosine similarity ≥ 0.50 (all-MiniLM-L6-v2) |
| Occurrence datetime | Within ±60 s of ground truth |

A scenario passes only when every applicable criterion is met.

---

### Track A — Synthetic benchmark

Ten hand-crafted scenarios with known topology and injected faults. Useful for iterating on the agent prompt without running against real data.

```bash
python eval/run_eval.py              # all 10 scenarios
python eval/run_eval.py --mock       # mock LLM, no API key needed
python eval/run_eval.py --difficulty easy
```

Sample result:

```
Class         Total     Correct   Accuracy
easy          3         2         66.7%
medium        3         3         100.0%
hard          4         3         75.0%
Total         10        8         80.0%
```

---

### Track B — Real OpenRCA Bank telemetry

27 incidents from the [OpenRCA Bank dataset](https://github.com/microsoft/OpenRCA) — a Java-based banking microservices system with 14 pods. Requires the `Bank/` dataset directory at the project root.

```bash
python eval/run_openrca_eval.py              # 27 Bank incidents
python eval/run_openrca_eval.py --mock       # no API key needed
python eval/run_openrca_eval.py --n 5        # quick test with 5 incidents
```

Sample result:

```
Class         Total     Full pass   Avg score
easy          2         1           0.71
medium        18        4           0.52
hard          7         1           0.38
Total         27        6           0.49
```

---

### Track C — RCAEval RE3-OB (code-level faults)

30 cases from the [RCAEval RE3-OB dataset](https://github.com/phamquiluan/RCAEval) — real telemetry from the Online Boutique microservices demo with deliberately injected code-level faults (wrong parameters, missing exception handlers, wrong return values). This is the primary benchmark for RootScout's codebase-context moat.

#### Dataset structure

```
data/RE3/RE3-OB/
  cartservice_f1/          # service broken + fault type
    1/                     # run 1 (same fault, different day)
      inject_time.txt      # Unix timestamp of fault injection
      simple_metrics.csv   # CPU/mem/latency/errors per second per service
      logs.csv             # all log lines from all services (~65k rows)
    2/
    3/
  emailservice_f3/
    ...
```

The ground truth is encoded in the directory name: `cartservice_f1` means cartservice was broken with a type F1 fault (wrong parameter).

#### Fault types

| Type | What was injected | Runtime signal |
|---|---|---|
| F1 | Wrong argument type passed to function | Stack trace + OverflowException |
| F2 | Missing function call | Silent misbehaviour, no crash |
| F3 | Missing exception handler | Exception propagates up, gRPC handler crashes |
| F4 | Wrong control flow | Wrong code path, bad results |
| F5 | Wrong return value | Downstream receives bad data |

#### Run

```bash
# full eval — all 30 cases
python eval/run_rcaeval_eval.py --model claude-sonnet

# quick sanity check — 5 cases, no API key needed
python eval/run_rcaeval_eval.py --mock --n 5

# specific fault types only
python eval/run_rcaeval_eval.py --fault-types F1 F3 --model claude-opus

# disable GitHub code fetching (faster, offline-safe)
python eval/run_rcaeval_eval.py --model claude-sonnet --no-code

# custom data directory
python eval/run_rcaeval_eval.py --data-dir /path/to/RE3-OB
```

#### Results

| Model | Component accuracy | Avg score | F1 | F2 | F3 | F4 | F5 |
|---|---|---|---|---|---|---|---|
| Claude Opus 4.6 | **87%** | 0.43 | 56% | 100% | 100% | 100% | 100% |
| Claude Sonnet 4.6 | 67% | 0.33 | 33% | 100% | 83% | 50% | 100% |
| Gemini 2.5 Flash | 0% | 0.00 | — | — | — | — | — |

Gemini results are invalid — API key was expired during the run.

**Component accuracy is the primary metric.** The reason score is near-zero across all models because the expected reasons are short labels (`"incorrect parameter passed to function"`) while the agent outputs verbose SRE explanations — cosine similarity between these is low even when the meaning is correct.

#### Why codebase context matters

When RootScout detects a stack trace in logs it fetches the actual source code from GitHub and includes it in the prompt. Without this, the agent reasons only from metric patterns and can misattribute the root cause to an upstream service that happened to show the earliest metric spike. With the source code, it can read the bug directly.

This is visible in the F1 cases (wrong parameter): telemetry-only attribution is 33% for Sonnet; with code context the agent can identify the OverflowException in `RedisCartStore.cs:54` and pin the correct service.

---

## Known limitations

- **Reason scoring is miscalibrated for RE3-OB.** Expected reasons are fault-type labels, not natural language explanations, so cosine similarity is low even when the agent is correct. Component accuracy is the meaningful metric.
- **Datetime scoring on Track B is not genuine.** The fault timestamp is taken directly from `record.csv` rather than predicted by the agent.
- **No trace topology on real data.** `trace_span.csv` uses internal container IDs that don't map to pod names, so a static hand-written topology is used.
- **Noisy anomaly detection.** During real incidents many services spike simultaneously, making causal isolation harder. On RE3-OB most nodes are flagged as error — the stack trace is the key discriminating signal.
- **Single system evaluated on Track C.** RCAEval also includes Sock Shop and Train Ticket datasets.

---

## Project layout

```
graph/              Graph construction, context retrieval, RCA agent
llm_integration/    Gemini, Claude, and OpenAI client wrappers
eval/               Evaluation scripts and scenarios
  run_eval.py           Track A — synthetic
  run_openrca_eval.py   Track B — Bank telemetry
  run_rcaeval_eval.py   Track C — RE3-OB code-level faults
  rcaeval_loader.py     RE3-OB scenario loader
  rcaeval_graph_adapter.py  Telemetry → GraphBuilder for RE3-OB
  rcaeval_code_fetcher.py   GitHub source code fetcher
RootScout/          OTel ingester service (FastAPI)
Ingester/           GitHub webhook ingester
demo_rcaeval.py     Live demo — Slack in, agent traversal, Slack out
demo_slack.py       Simpler Slack integration demo
```
