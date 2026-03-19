# RootScout Evaluation

This directory contains three evaluation tracks for RootScout. Each track measures whether the agent correctly identifies the **root cause component** and **reason** for an incident, using [OpenRCA](https://github.com/microsoft/OpenRCA) scoring.

---

## Scoring methodology

Every incident is scored on up to three criteria depending on the task type:

| Criterion | Match method |
|---|---|
| Root cause component | Exact string match |
| Root cause reason | Cosine similarity ≥ 0.50 (all-MiniLM-L6-v2) |
| Occurrence datetime | Within ±60 s of ground truth |

A scenario scores 1.0 only when every applicable criterion passes. Partial credit is given when some criteria pass.

---

## Prerequisites

```bash
pip install -r requirements.txt
pip install -r requirements_eval.txt
```

Set up your `.env` file at the project root:

```bash
cp .env.example .env
```

Required keys depending on which LLM you use:

```bash
GEMINI_API_KEY=...          # for --model gemini (default)
ANTHROPIC_API_KEY=...       # for --model claude-sonnet or claude-opus
OPENAI_API_KEY=...          # for --model openai
GITHUB_TOKEN=...            # optional — raises GitHub rate limit from 60 to 5000 req/hr
                            # needed for code fetching in Track C
```

---

## Track A — Synthetic benchmark

Ten hand-crafted scenarios with known topology and injected faults. No external data download required. Useful for sanity-checking the pipeline and iterating on the agent prompt without API costs.

**Run:**

```bash
# All 10 scenarios
python eval/run_eval.py

# No API key needed (mock LLM, fake predictions)
python eval/run_eval.py --mock

# Filter by difficulty
python eval/run_eval.py --difficulty easy
python eval/run_eval.py --difficulty medium
python eval/run_eval.py --difficulty hard
```

**Sample result:**

```
Class         Total     Correct   Accuracy
easy          3         2         66.7%
medium        3         3         100.0%
hard          4         3         75.0%
Total         10        8         80.0%
```

---

## Track B — OpenRCA Bank telemetry

27 real incidents from the [OpenRCA Bank dataset](https://github.com/microsoft/OpenRCA) — a Java-based banking microservices system with 14 pods and infrastructure-level faults (CPU throttle, memory pressure, network partition).

**Dataset setup:**

Download the Bank dataset and place it at the project root:

```bash
# The Bank/ directory should contain incident subdirectories
ls Bank/
# incident_001/  incident_002/  ...
```

**Run:**

```bash
# All 27 incidents
python eval/run_openrca_eval.py

# Quick test — no API key needed
python eval/run_openrca_eval.py --mock

# Limit to first N incidents
python eval/run_openrca_eval.py --n 5

# Specific LLM
python eval/run_openrca_eval.py --model claude-sonnet
```

**Sample result:**

```
Class         Total     Full pass   Avg score
easy          2         1           0.71
medium        18        4           0.52
hard          7         1           0.38
Total         27        6           0.49
```

---

## Track C — RCAEval RE3-OB (code-level faults)

The primary benchmark. Real telemetry from the [Online Boutique](https://github.com/GoogleCloudPlatform/microservices-demo) microservices demo with deliberately injected code-level faults. Unlike Track B (infrastructure faults), RE3-OB faults are in the application code — wrong parameters, missing exception handlers, wrong return values. Logs contain stack traces that point directly to the faulty line.

### Dataset structure

```
data/RE3-OB/
  cartservice_F1_1/        # {service}_{fault_type}_{run_number}
    inject_time.txt        # Unix timestamp of fault injection (UTC)
    simple_metrics.csv     # CPU/mem/latency/errors per second per service
    logs.csv               # all log lines from all services (~65k rows)
    data.csv               # wide-format raw metrics
  cartservice_F1_2/
  cartservice_F1_3/
  emailservice_F3_1/
  ...
```

**The ground truth is encoded in the folder name:**
- `cartservice_F1_1` → `cartservice` was broken with a type `F1` fault, run 1
- `inject_time.txt` → when the fault was injected

### Fault types

| Type | What was injected | Runtime signal | Difficulty |
|---|---|---|---|
| F1 | Wrong argument passed to function | Stack trace + OverflowException | Easy |
| F2 | Missing function call | Silent misbehaviour, no crash | Medium |
| F3 | Missing exception handler | Exception propagates, gRPC handler crashes | Medium |
| F4 | Wrong control flow / complex interactions | Wrong code path, bad results | Hard |
| F5 | Wrong return value | Downstream receives bad data | Easy |

### Dataset download

```bash
git clone https://github.com/phamquiluan/RCAEval /tmp/RCAEval
cd /tmp/RCAEval
pip install -e .
python main.py --download --dataset RE3-OB
cp -r data/RE3-OB <project_root>/data/RE3-OB
```

This downloads ~200 MB into `data/RE3-OB/`.

Verify the download:

```bash
ls data/RE3-OB/ | head -10
# adservice_F3_1/
# adservice_F3_2/
# cartservice_F1_1/
# ...
```

Each case directory must contain `inject_time.txt`, `logs.csv`, and either `simple_metrics.csv` or `data.csv`. Cases missing `inject_time.txt` are skipped automatically.

### Run

```bash
# Full evaluation — all cases, default LLM (Gemini)
python eval/run_rcaeval_eval.py

# Quick sanity check — 5 cases, no API key needed
python eval/run_rcaeval_eval.py --mock --n 5

# Run with Claude Sonnet
python eval/run_rcaeval_eval.py --model claude-sonnet

# Run with Claude Opus
python eval/run_rcaeval_eval.py --model claude-opus

# Specific fault types only
python eval/run_rcaeval_eval.py --fault-types F1 F3

# Filter by difficulty
python eval/run_rcaeval_eval.py --difficulty easy

# Disable GitHub code fetching (faster, no GITHUB_TOKEN needed)
python eval/run_rcaeval_eval.py --model claude-sonnet --no-code

# Custom data directory
python eval/run_rcaeval_eval.py --data-dir /path/to/RE3-OB

# Save results to a specific path
python eval/run_rcaeval_eval.py --output eval/results/my_run.csv
```

### CLI flags reference

| Flag | Default | Description |
|---|---|---|
| `--model` | `gemini` | LLM provider: `gemini`, `claude-sonnet`, `claude-opus`, `openai` |
| `--mock` | off | Use MockClient — no API key needed, predictions are fake |
| `--n` | all | Limit to first N scenarios |
| `--fault-types` | all | Filter: `F1` `F2` `F3` `F4` `F5` (space-separated) |
| `--difficulty` | all | Filter: `easy`, `medium`, `hard` |
| `--data-dir` | `data/RE3/RE3-OB` | Path to RE3-OB directory |
| `--no-code` | off | Disable GitHub source code fetching |
| `--output` | auto | Output CSV path (default: `eval/results/re3_run_<timestamp>.csv`) |

### Output files

Each run writes four files to `eval/results/`:

| File | Contents |
|---|---|
| `re3_run_<timestamp>.csv` | Full results: scenario id, score, prediction, error per case |
| `re3_run_<timestamp>_predictions.csv` | OpenRCA-format predictions |
| `re3_run_<timestamp>_query.csv` | Ground truth in OpenRCA format |
| `re3_run_<timestamp>_report.csv` | Final per-task-type score report |

### Results

| Model | Component accuracy | Avg score | F1 | F2 | F3 | F4 | F5 |
|---|---|---|---|---|---|---|---|
| Claude Opus 4.6 | **87%** | 0.43 | 56% | 100% | 100% | 100% | 100% |
| Claude Sonnet 4.6 | 67% | 0.33 | 33% | 100% | 83% | 50% | 100% |

> **Note on reason scoring:** The avg score is low because expected reasons are short fault-type labels (`"incorrect parameter passed to function"`) while the agent outputs verbose SRE explanations. Cosine similarity between these is low even when the agent is correct. **Component accuracy is the meaningful metric.**

### How code fetching works

When RootScout detects a stack trace in logs it parses the filename and line number, fetches the surrounding source code from GitHub ([microservices-demo](https://github.com/GoogleCloudPlatform/microservices-demo)), and includes it in the LLM prompt. The agent can read the exact faulty line rather than inferring from metric patterns alone.

Results are cached to `.cache/github_code/` so each file is fetched at most once across runs. Unauthenticated GitHub access allows 60 requests/hr — set `GITHUB_TOKEN` in `.env` for 5000 requests/hr.

Use `--no-code` to disable this and run offline.

---

## Common issues

**`No valid RE3-OB cases found`**
The `--data-dir` path is wrong or the dataset wasn't downloaded. Check that `data/RE3-OB/cartservice_F1_1/inject_time.txt` exists.

**`Could not initialise 'gemini'` / falls back to MockClient**
Your API key is missing or wrong in `.env`. MockClient runs the pipeline but predictions are hardcoded fakes — scores will be 0.

**GitHub rate limit errors during code fetching**
Set `GITHUB_TOKEN` in `.env` or use `--no-code` to disable fetching.

**`sentence-transformers` missing**
Run `pip install -r requirements_eval.txt`. The reason scoring requires `sentence-transformers`.
