#!/usr/bin/env python3
"""
demo_rcaeval.py — RootScout Live Demo
======================================

Flow (≈75 seconds):
  10s   Slack alert arrives — checkout failures on Online Boutique
  40s   Agent traverses: telemetry → call graph → stack trace → source code
  15s   Claude reasons, produces RCA + recommended action
  10s   Resolution posted back to Slack + payoff line

Scenario: RE3-OB cartservice_f1/1
  Fault:   Wrong parameter type passed to Redis AddItem → OverflowException
  Signal:  C# stack trace in cartservice logs + latency spike across checkout flow
  Moat:    Agent fetches the *exact faulty code line* from GitHub before prompting

Run:
    python demo_rcaeval.py                        # dry-run (no real Slack)
    SLACK_BOT_TOKEN=xoxb-... python demo_rcaeval.py   # real Slack posts
"""

import os
import sys
import time
import json
import textwrap
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

# ── colour palette ──────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[31m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
BLUE   = "\033[34m"
MAGENTA= "\033[35m"
WHITE  = "\033[97m"
GREY   = "\033[90m"
BG_RED = "\033[41m"

def _c(color, text): return f"{color}{text}{RESET}"
def banner(text, w=70, char="═"):
    pad = max(0, w - len(text) - 4)
    return f"\n{char*2}  {BOLD}{text}{RESET}  {char*(pad)}"

def step_header(n, title):
    print(f"\n{BOLD}{CYAN}┌{'─'*66}┐{RESET}")
    print(f"{BOLD}{CYAN}│  STEP {n}: {title:<57}│{RESET}")
    print(f"{BOLD}{CYAN}└{'─'*66}┘{RESET}")

def log_info(msg):  print(f"  {GREY}│{RESET}  {msg}")
def log_ok(msg):    print(f"  {GREEN}✓{RESET}  {msg}")
def log_warn(msg):  print(f"  {YELLOW}⚠{RESET}  {msg}")
def log_event(msg): print(f"  {MAGENTA}→{RESET}  {msg}")
def log_code(msg):  print(f"  {CYAN}⌂{RESET}  {msg}")
def log_llm(msg):   print(f"  {BLUE}◈{RESET}  {msg}")

def _pause(s=0.8): time.sleep(s)

def _typewrite(text, delay=0.018):
    """Print text character by character for dramatic effect."""
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)
    print()


# ── Slack renderer (terminal) ───────────────────────────────────────────────

def _slack_box(header, fields, colour=YELLOW):
    w = 64
    print(f"\n  {colour}╔{'═'*w}╗{RESET}")
    print(f"  {colour}║{RESET}  {BOLD}Slack{RESET}{GREY} #incidents{RESET}{' '*(w-13)}{colour}║{RESET}")
    print(f"  {colour}╠{'═'*w}╣{RESET}")
    for line in header:
        padded = line[:w-2].ljust(w-2)
        print(f"  {colour}║{RESET}  {padded}  {colour}║{RESET}")
    if fields:
        print(f"  {colour}╠{'─'*w}╣{RESET}")
    for k, v in fields:
        kstr = f"{BOLD}{k}{RESET}"
        vstr = str(v)
        # wrap long values
        wrapped = textwrap.wrap(vstr, width=w-4-len(k)-2) or [""]
        first = True
        for wline in wrapped:
            if first:
                row = f"{kstr}  {wline}"
                first = False
            else:
                row = f"{' '*(len(k)+2)}{wline}"
            padded = row.ljust(w)
            print(f"  {colour}║{RESET}  {padded}{colour}║{RESET}")
    print(f"  {colour}╚{'═'*w}╝{RESET}")


def post_slack_alert(service, signal, detail, notifier=None):
    """Print a Slack alert block and optionally post to real Slack."""
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
    _slack_box(
        header=[
            f"🚨  {_c(BOLD+RED, 'INCIDENT ALERT')}  —  {service}  is  {_c(RED,'ERROR')}",
            f"    Detected at {ts}",
        ],
        fields=[
            ("Signal",  signal),
            ("Detail",  detail),
            ("Action",  f"Run `/rca {service}` to investigate"),
        ],
        colour=RED,
    )
    if notifier:
        try:
            # SlackNotifier._safe_post already prints errors internally
            notifier.post_incident_alert(
                service=service, status="error", signal=signal, detail=detail
            )
        except Exception as e:
            log_warn(f"Slack post failed: {e}")


def post_slack_rca(focus_service, report, notifier=None):
    """Print a Slack RCA block and optionally post to real Slack."""
    root  = report.get("root_cause_service", "?")
    conf  = float(report.get("confidence", 0.0))
    why   = report.get("reasoning", "")
    fix   = report.get("recommended_action", "")
    conf_emoji = "🟢" if conf >= 0.8 else "🟡" if conf >= 0.5 else "🔴"

    _slack_box(
        header=[
            f"🔍  {_c(BOLD+GREEN, 'RCA COMPLETE')}  —  {focus_service}",
        ],
        fields=[
            ("Root cause",  f"{root}"),
            ("Confidence",  f"{conf_emoji}  {conf*100:.0f}%"),
            ("Reasoning",   why[:240] + ("…" if len(why) > 240 else "")),
            ("Fix",         fix),
        ],
        colour=GREEN,
    )
    if notifier:
        try:
            notifier.post_rca_report(focus_service=focus_service, report=report)
        except Exception as e:
            log_warn(f"Slack post failed: {e}")


# ── BFS traversal with live logging ─────────────────────────────────────────

def traverse_graph_verbose(graph_builder, start_service):
    """
    Walk the dependency graph from start_service using BFS.
    Print each node as it is visited — this is the "agent thinking" window.
    Returns the context packet.
    """
    import networkx as nx
    graph = graph_builder.graph

    print()
    print(f"  {DIM}Causal Dependency Graph  (BFS from '{start_service}'){RESET}")
    print(f"  {DIM}{'─'*60}{RESET}")

    visited = []
    queue   = [start_service]
    seen    = set()

    while queue:
        node = queue.pop(0)
        if node in seen:
            continue
        seen.add(node)
        visited.append(node)

        node_data = graph.nodes.get(node, {})
        status    = node_data.get("status", "unknown")
        events    = node_data.get("recent_events", [])
        children  = list(graph.successors(node))

        depth = nx.shortest_path_length(graph, start_service, node) if node != start_service else 0
        indent = "  " * depth
        status_icon = _c(RED, "🔴") if status == "error" else _c(GREEN, "🟢") if status == "ok" else "⚪"

        _pause(0.35)
        print(f"  {GREY}│{RESET}  {indent}{status_icon}  {BOLD}{node}{RESET}  {DIM}[{status}]{RESET}")

        # Show top 2 events
        for ev in events[:2]:
            kind    = ev.get("kind", "?")
            summary = ev.get("summary", "")[:80]
            src     = ev.get("source", "?")
            icon    = "🔥" if kind == "code_fault" else "📊" if src == "metric" else "📋"
            print(f"  {GREY}│{RESET}  {indent}  {icon}  {DIM}[{src}/{kind}]{RESET}  {summary}")

        if children:
            print(f"  {GREY}│{RESET}  {indent}  {DIM}↳ calls: {', '.join(children)}{RESET}")

        queue.extend(c for c in children if c not in seen)

    print(f"  {DIM}{'─'*60}{RESET}")
    print(f"  {DIM}  Traversed {len(visited)} services in dependency graph{RESET}")

    # Build context packet (same shape as ContextRetriever)
    context = {"focus_service": start_service, "related_nodes": []}
    for node in visited:
        nd = graph.nodes.get(node, {})
        context["related_nodes"].append({
            "service": node,
            "status":  nd.get("status", "unknown"),
            "version": nd.get("version", "unknown"),
            "events":  nd.get("recent_events", []),
        })
    return context


# ── System prompt preview ────────────────────────────────────────────────────

def show_system_prompt(context):
    """Reconstruct and print the system prompt that will be sent to the LLM."""
    from graph.agent import RCAAgent
    from llm_integration.client import MockClient
    dummy_agent = RCAAgent(client=MockClient())
    prompt = dummy_agent._construct_prompt(context)

    lines = prompt.split("\n")
    w = 66

    print(f"\n  {BOLD}{BLUE}╔{'═'*w}╗{RESET}")
    print(f"  {BOLD}{BLUE}║{RESET}  {'SYSTEM PROMPT  (sent to Claude)':<{w-2}}{BOLD}{BLUE}║{RESET}")
    print(f"  {BOLD}{BLUE}╠{'═'*w}╣{RESET}")
    for line in lines:
        # break long lines
        for chunk in textwrap.wrap(line, width=w-4) or [""]:
            padded = chunk.ljust(w-2)
            print(f"  {BOLD}{BLUE}║{RESET}  {padded}  {BOLD}{BLUE}║{RESET}")
    print(f"  {BOLD}{BLUE}╚{'═'*w}╝{RESET}")
    return prompt


# ── Main demo ────────────────────────────────────────────────────────────────

def main():
    print(banner("RootScout  ·  Live Demo", w=70))
    print(f"\n  {DIM}Scenario : Online Boutique · cartservice F1 (code-level fault){RESET}")
    print(f"  {DIM}Dataset  : RE3-OB (RCAEval) — real telemetry, real stack traces{RESET}")
    print(f"  {DIM}Moat     : agent fetches the faulty source line from GitHub{RESET}\n")

    # ── Slack env setup ──────────────────────────────────────────────────────
    slack_token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    notifier    = None
    if slack_token:
        from RootScout.slack_connector import SlackConfig, SlackNotifier
        cfg      = SlackConfig(
            bot_token=slack_token,
            signing_secret=os.getenv("SLACK_SIGNING_SECRET", ""),
            alert_channel=os.getenv("SLACK_ALERT_CHANNEL", "#incidents"),
            rca_channel=os.getenv("SLACK_RCA_CHANNEL", ""),
            alert_cooldown_seconds=0,
        )
        notifier = SlackNotifier(cfg)
        log_ok(f"Slack connected → {cfg.alert_channel}")
    else:
        log_warn("SLACK_BOT_TOKEN not set — printing Slack messages to terminal (dry-run)")

    _pause(0.5)

    # ════════════════════════════════════════════════════════════════════════
    # STEP 1 — Slack alert arrives
    # ════════════════════════════════════════════════════════════════════════
    step_header(1, "Slack alert arrives")
    _pause(0.5)

    sys.stdout.write(f"\n  {DIM}incoming message …{RESET}  ")
    _typewrite("🚨  PagerDuty → #incidents", delay=0.04)
    _pause(0.4)

    post_slack_alert(
        service="cartservice",
        signal="trace + log  (OverflowException, p99 latency +340 ms)",
        detail=(
            "15% of checkout requests failing. "
            "System.OverflowException in RedisCartStore detected at 05:43 UTC."
        ),
        notifier=notifier,
    )
    _pause(1.0)

    # ════════════════════════════════════════════════════════════════════════
    # STEP 2 — Load RE3-OB telemetry
    # ════════════════════════════════════════════════════════════════════════
    step_header(2, "Load telemetry  (±15 min window)")

    DATA_DIR = "data/RE3/RE3-OB"
    if not os.path.isdir(DATA_DIR):
        log_warn(f"RE3-OB data not found at {DATA_DIR}")
        log_warn("Download: python -c \"import sys; sys.path.insert(0,'/tmp/RCAEval'); "
                 "from RCAEval.utility import download_re3ob_dataset; "
                 "download_re3ob_dataset('data/RE3')\"")
        sys.exit(1)

    from eval.rcaeval_loader import load_re3_scenarios
    from eval.rcaeval_graph_adapter import build_re3_graph

    log_info("Scanning data/RE3/RE3-OB for cartservice F1 case …")
    _pause(0.3)
    scenarios = load_re3_scenarios(DATA_DIR, fault_types=["F1"])
    # Pick cartservice case 1
    scenario = next(
        (s for s in scenarios if "cartservice" in s["id"] and "001" in s["id"]),
        scenarios[0],
    )

    log_ok(f"Scenario   : {scenario['id']}")
    log_ok(f"Inject time: {scenario['re3_inject_time'].strftime('%Y-%m-%d %H:%M:%S UTC')}")
    log_ok(f"GT service : {scenario['ground_truth']['root_cause_component']}")
    log_ok(f"GT reason  : {scenario['ground_truth']['root_cause_reason']}")
    _pause(0.5)

    log_info("Reading simple_metrics.csv  (cpu / mem / latency / error_rate) …")
    _pause(0.4)
    log_info("Reading logs.csv  (container_name, message) …")
    _pause(0.4)

    # Build graph — fetch_code=True so GitHub source snippets are pulled
    log_info("Building causal dependency graph …")
    _pause(0.2)
    graph_builder = build_re3_graph(scenario, fetch_code=True)

    # Count signals
    total_events = sum(
        len(graph_builder.graph.nodes[n].get("recent_events", []))
        for n in graph_builder.graph.nodes
    )
    error_nodes = [
        n for n in graph_builder.graph.nodes
        if graph_builder.graph.nodes[n].get("status") == "error"
    ]
    code_fault_nodes = [
        n for n in graph_builder.graph.nodes
        if any(
            e.get("kind") == "code_fault"
            for e in graph_builder.graph.nodes[n].get("recent_events", [])
        )
    ]
    snippet_nodes = [
        n for n in graph_builder.graph.nodes
        if any(
            e.get("kind") == "code_snippet"
            for e in graph_builder.graph.nodes[n].get("recent_events", [])
        )
    ]

    print()
    log_ok(f"Graph built  : {graph_builder.graph.number_of_nodes()} services, "
           f"{graph_builder.graph.number_of_edges()} edges")
    log_ok(f"Total events : {total_events}")
    log_warn(f"Error nodes  : {error_nodes}")
    if code_fault_nodes:
        log_event(f"Stack traces : {code_fault_nodes}  ← 🔥 code-level signal")
    if snippet_nodes:
        log_code(f"Code fetched : {snippet_nodes}  ← GitHub source snippet attached")

    _pause(0.8)

    # ════════════════════════════════════════════════════════════════════════
    # STEP 3 — Walk the call graph (the "thinking" window)
    # ════════════════════════════════════════════════════════════════════════
    step_header(3, "Traversing call graph  (BFS from 'frontend')")
    _pause(0.3)

    context = traverse_graph_verbose(graph_builder, "frontend")
    _pause(0.5)

    # Show the actual stack trace that was detected
    print()
    log_event("Stack trace detected in  cartservice:")
    for node in graph_builder.graph.nodes:
        for ev in graph_builder.graph.nodes[node].get("recent_events", []):
            if ev.get("kind") == "code_fault":
                trace_msg = ev.get("payload", {}).get("log_message", "")
                # Show first 4 meaningful lines
                lines = [l for l in trace_msg.split("\n") if l.strip()][:4]
                for l in lines:
                    print(f"  {RED}│{RESET}  {DIM}{l.strip()[:80]}{RESET}")
                break
        else:
            continue
        break

    # Show code snippet if fetched
    _pause(0.3)
    for node in graph_builder.graph.nodes:
        for ev in graph_builder.graph.nodes[node].get("recent_events", []):
            if ev.get("kind") == "code_snippet":
                fname = ev["payload"].get("filename", "?")
                patch = ev["payload"].get("patch", "")
                url   = ev["payload"].get("github_url", "")
                print()
                log_code(f"Source fetched from GitHub → {fname}")
                if url:
                    print(f"  {DIM}  {url}{RESET}")
                print()
                # Print snippet with line numbers, highlight the error line
                for line in patch.split("\n")[:20]:
                    if line.startswith(">>>"):
                        print(f"  {RED}{BOLD}{line}{RESET}")
                    else:
                        print(f"  {DIM}{line}{RESET}")
                break
        else:
            continue
        break

    _pause(1.0)

    # ════════════════════════════════════════════════════════════════════════
    # STEP 4 — Show the system prompt
    # ════════════════════════════════════════════════════════════════════════
    step_header(4, "System prompt  (assembled for LLM)")
    _pause(0.4)
    show_system_prompt(context)
    _pause(1.0)

    # ════════════════════════════════════════════════════════════════════════
    # STEP 5 — Send to Claude, get RCA
    # ════════════════════════════════════════════════════════════════════════
    step_header(5, "LLM analysis  (Claude Sonnet 4.6)")

    from llm_integration.client import ClaudeClient, MockClient
    from graph.agent import RCAAgent

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        try:
            llm = ClaudeClient(model="claude-sonnet-4-6")
            log_ok("Using Claude Sonnet 4.6  (Anthropic API)")
        except Exception as e:
            log_warn(f"Claude unavailable ({e}) — falling back to MockClient")
            llm = MockClient()
    else:
        log_warn("ANTHROPIC_API_KEY not set — using MockClient (output will be fake)")
        llm = MockClient()

    _pause(0.5)

    agent = RCAAgent(client=llm, github_output_path=None)

    log_llm("Sending context to Claude …")
    _pause(0.3)

    t0     = time.time()
    report = agent.analyze(context)
    elapsed = time.time() - t0

    log_ok(f"Response received in {elapsed:.1f}s")
    _pause(0.4)

    root_svc = report.get("root_cause_service", "unknown")
    conf     = float(report.get("confidence", 0.0))
    why      = report.get("reasoning", "")
    fix      = report.get("recommended_action", "")
    root_dt  = report.get("root_cause_datetime", "")

    print()
    print(f"  {BOLD}Root cause service :{RESET}  {_c(RED+BOLD, root_svc)}")
    print(f"  {BOLD}Confidence         :{RESET}  {conf*100:.0f}%")
    if root_dt:
        print(f"  {BOLD}Fault onset        :{RESET}  {root_dt}")
    print()
    print(f"  {BOLD}Reasoning:{RESET}")
    for chunk in textwrap.wrap(why, width=64):
        print(f"    {chunk}")
    print()
    print(f"  {BOLD}Recommended action:{RESET}")
    for chunk in textwrap.wrap(fix, width=64):
        print(f"    {chunk}")

    _pause(1.0)

    # ════════════════════════════════════════════════════════════════════════
    # STEP 6 — Post RCA back to Slack
    # ════════════════════════════════════════════════════════════════════════
    step_header(6, "Post RCA back to Slack")
    _pause(0.3)

    post_slack_rca(
        focus_service="cartservice",
        report=report,
        notifier=notifier,
    )

    _pause(1.0)

    # ════════════════════════════════════════════════════════════════════════
    # Payoff line
    # ════════════════════════════════════════════════════════════════════════
    print(f"\n{BOLD}{'═'*70}{RESET}")
    print(f"\n  {_c(GREEN+BOLD, 'Incident resolved.')}\n")
    _typewrite(
        "  What used to take an on-call engineer 45 minutes "
        f"took {elapsed:.0f} seconds.",
        delay=0.025,
    )
    print()
    print(f"  {DIM}With codebase context: agent read the exact faulty line before prompting.{RESET}")
    print(f"  {DIM}Without it: pure telemetry correlation — no code signal, lower accuracy.{RESET}")
    print(f"\n{BOLD}{'═'*70}{RESET}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Interrupted.")
